# Hazmat Tier II Reporting API — Product Requirements Document

## 1. Introduction

Facilities that store hazardous chemicals in the United States operate under the Emergency Planning and Community Right-to-Know Act (EPCRA). They must inventory what they hold, determine which chemicals cross federal reporting thresholds, file an annual Tier II report with the appropriate fee, maintain a safety-data-sheet (SDS) repository, notify emergency-planning bodies when a release exceeds its reportable quantity, and submit to periodic inspection and enforcement. This service is the system of record that ties all of those obligations together for a state regulatory authority, the facility operators it oversees, and the Local Emergency Planning Committees that coordinate community response.

The platform is organized as a flat collection of resources mounted under the `/epcra` prefix. A central catalog of chemicals is shared across every facility, while each facility owns its own inventory declarations, filings, safety data sheets, release notifications, permits, inspections, compliance cases, and risk-management plans. Much of the system's behavior is not stored directly but is instead reconciled every time a facility is read: its compliance posture, aggregate hazard index, outstanding fee balance, and risk-management obligation are all computed from the current state of its subordinate records. A handful of cascading side effects — most importantly, the automatic enforcement action triggered by a large chemical release — bind these resources together so that a single event can ripple through cases, postures, and permits in one atomic step.

Because regulatory review turns on dates and deadlines, the system does not read the wall clock. It maintains a **logical clock** that a regulator advances explicitly, and every temporal decision — filing lateness, permit expiry, inspector scheduling gaps, release timing, and risk-management due dates — is evaluated against that logical clock.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is missing or its role is not recognized, the request is rejected with `ERR_MISSING_AUTH_HEADER` (HTTP 400). When the headers are well-formed but the role is not permitted to perform the requested operation — or a facility operator attempts to act on a facility it does not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Three roles exist, spelled exactly as follows:

- **`Regulator`** — the state/SERC regulatory authority. Regulators register facilities and catalog chemicals, review Tier II filings, issue permits, schedule and run inspections, and open, review, and resolve enforcement cases. When `X-User-Role` is `Regulator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it contextually but never compares it to any entity's `id`.
- **`FacilityOperator`** — the operator of a single facility. When `X-User-Role` is `FacilityOperator`, `X-User-ID` is the `id` of the acting `Facility`; ownership checks on any resource that references a facility compare that resource's `facility_id` to `X-User-ID`. A facility operator may only manage inventory, filings, SDS documents, releases, LEPC notices, risk-management plans, and emergency-response linkage for its own facility.
- **`LEPCCoordinator`** — a Local Emergency Planning Committee coordinator. When `X-User-Role` is `LEPCCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. Its sole write capability is acknowledging LEPC/SERC/NRC notices.

All three roles may read any resource under `/epcra` through the GET endpoints. Write operations are partitioned exclusively by role as described throughout §3 and summarized in §4.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

### 2.3. Pagination

All list endpoints are paginated through two query parameters. The `limit` parameter controls page size; it defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter controls how many records are skipped from the start of the result set; it defaults to 0 and has a minimum of 0. Results are always returned sorted by `created_at` in ascending order, so that the earliest-created record appears first.

For every list response, the `meta` object carries four pagination fields: `limit` and `offset` echo the effective values applied to the query, `total_count` reports the total number of records matching the filter before pagination, and `has_more` is `true` exactly when records remain beyond the current page.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is assigned a server-minted `id` — a UUID with no type prefix — at creation, and every resource carries a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits. Every entity in this system also participates in the mutation-tracking contract: each carries an `updated_at` timestamp (same format as `created_at`) and an integer `version` that begins at 1 when the resource is created and increments by 1 on every mutation of that resource. A resource's `updated_at` is refreshed to the current logical clock whenever the resource is mutated, whether by a direct write or by a cascade originating elsewhere.

When a facility's derived fields are recomputed on read (see §2.6), that recomputation is a reconciliation of a projection and does not by itself bump `version` or `updated_at`; only an actual state-changing operation on the facility — such as linking an emergency-response plan or superseding an SDS — advances the facility's `version`.

### 2.5. The Logical Clock

The server maintains a single logical clock that stands in for "now" everywhere in the system. Its startup default is `2026-03-01T00:00:00Z`; before any clock write the clock reads exactly this default and never falls back to wall-clock time. A regulator may set the clock to any instant by supplying a `to_iso8601` value. Every temporal comparison in the system reads this clock: a filing's lateness, a permit's expiry, a release's timing, an inspector's scheduling gap, and a risk-management plan's due window are all measured against it. Timestamps the system stamps onto records — a filing's `submitted_at`, a notice's `sent_at` — are taken from the logical clock at the moment of the operation.

### 2.6. Derived Facility State Reconciled on Read

A `Facility` exposes several fields that are never written directly by a client but are recomputed from its subordinate records whenever the facility is read (whether individually or in a list):

- **`open_case_count`** is the number of the facility's compliance cases whose `status` is either `OPEN` or `UNDER_REVIEW`.
- **`compliance_posture`** is derived from those same open cases. If any open case has `origin` equal to `RELEASE_RQ_EXCEEDED` or `severity` equal to `HIGH`, the posture is `ENFORCEMENT`. Otherwise, if there is at least one open case, the posture is `DEFICIENT`. If there are no open cases, the posture is `COMPLIANT`. A newly registered facility has posture `COMPLIANT`.
- **`hazard_index`** is the facility's aggregate hazard score, described in §3.3. It defaults to 0.0 for a facility with no active inventory.
- **`total_outstanding_fee_cents`** is the facility's unpaid fee balance, described in §2.8 and §3.4. It defaults to 0.
- **`is_rmp_required`** is `true` exactly when the facility has at least one `ACTIVE` chemical inventory of an Extremely Hazardous Substance whose reportable amount reaches or exceeds that chemical's Threshold Planning Quantity, and `false` otherwise; it defaults to `false`.

These five projections must always reflect the facility's current subordinate state at read time. In addition, several write operations described in §3 explicitly recompute one or more of them as a side effect (for example, retiring an inventory row recomputes `hazard_index` and `is_rmp_required`, and opening or resolving a case recomputes `open_case_count` and `compliance_posture`).

### 2.7. Optimistic Concurrency Control on the SDS Repository

Uploading a safety data sheet is the one operation in this system guarded by optimistic concurrency, because a new sheet supersedes the prior active one for the same facility-and-chemical pair and therefore mutates the facility's SDS repository as a whole. An SDS upload request must carry an `expected_facility_version` field whose value equals the target facility's current `version`. If the facility's `version` has advanced since the client last observed it — meaning the client is operating on an out-of-date view of the repository — the upload is rejected with `ERR_STALE_FACILITY_VERSION` (HTTP 412). No other endpoint takes a version field; the SDS upload is the sole write governed by this stale-version check.

### 2.8. Monetary Precision and the Outstanding-Fee Ledger

All fees and penalties are expressed as integer cents. The only place rounding occurs in the fee calculation is the single late-penalty multiplication, which is rounded half up to a whole number of cents; likewise, each per-chemical hazard contribution is rounded half up to two decimal places (see §3.3). Wherever this document specifies "round half up," a value whose fractional part is exactly one half rounds away from zero.

A facility's `total_outstanding_fee_cents` is a ledger reconciled from its Tier II filings. It is the sum, over every filing whose `status` is `SUBMITTED` or `UNDER_REVIEW`, of that filing's `assessed_fee_cents` minus its `fee_paid_cents`; filings in `DRAFT`, `RETURNED_FOR_REVISION`, or `ACCEPTED` contribute nothing. This ledger is a conserved quantity: submitting a filing adds its assessed-minus-paid amount, and returning a filing both removes its contribution and zeroes its assessed fee, so that a submit-then-return round trip with no intervening payment restores the facility's outstanding total exactly. This balance is reconciled on any filing submit, return, payment, or acceptance, and per filing the assessed-minus-paid contribution is never treated as less than zero.

### 2.9. Validation Precedence and Nested Resource Resolution

When several conditions could reject the same request, they are evaluated in a fixed order so that the returned error is deterministic. Authentication comes first: a missing or unrecognized header (`ERR_MISSING_AUTH_HEADER`) is caught before anything else, followed by the role/ownership check (`ERR_UNAUTHORIZED`). Next, the request body is checked for well-formedness — required fields present, enum values valid, numeric amounts non-negative, and an EHS chemical carrying its `tpq_lbs` — which fails with `ERR_INVALID_REQUEST`. After that, referenced identifiers are resolved: any facility, chemical, inventory, filing, SDS, release, permit, inspection, case, risk-management plan, or path id that does not exist yields the corresponding not-found error (`ERR_FACILITY_NOT_FOUND`, `ERR_CHEMICAL_NOT_FOUND`, `ERR_INVENTORY_NOT_FOUND`, `ERR_FILING_NOT_FOUND`, `ERR_SDS_NOT_FOUND`, `ERR_RELEASE_NOT_FOUND`, `ERR_LEPC_NOTICE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, or `ERR_RMP_NOT_FOUND`), each HTTP 404.

Only after existence is confirmed does the optimistic-concurrency check on SDS upload run (`ERR_STALE_FACILITY_VERSION`), then the state-transition check that the target resource is in a state permitting the requested action (the `ERR_*_NOT_*` and `ERR_RELEASE_INVALID_STAGE` family, HTTP 409). Business-safety, referential, temporal, cross-entity, and fiscal checks described in §3 run after those structural checks. For endpoints whose path names a subordinate collection of a facility, the facility id in the path is resolved left to right before the subordinate collection is filtered, so a request against a non-existent facility fails with `ERR_FACILITY_NOT_FOUND` rather than returning an empty list.

## 3. Business Logic & Workflows

### 3.1. Facility Registration and Emergency-Response Linkage

A `Regulator` brings a regulated site into the system by registering it with a `name`, an `epa_facility_id`, a two-letter `state_code`, a `county` (which also names the LEPC district), and an `operator_name`. The `epa_facility_id` is the EPA facility registry identifier and must be unique across all facilities. At registration the facility's derived and system fields take their initial values: its `compliance_posture` is `COMPLIANT`, its `erp_status` is `NONE`, its `version` is 1, and its emergency-response contact fields are empty.

Every facility begins with **no emergency-response plan on file**. A `FacilityOperator` links or updates its own facility's plan by supplying a `contact_name`, a `contact_phone`, a `plan_ref` document reference, and a `linked_lepc_district`. This linkage populates the facility's `erp_contact_name`, `erp_contact_phone`, `erp_plan_ref`, and `erp_linked_lepc_district` fields respectively, flips `erp_status` from `NONE` to `ACTIVE`, and increments the facility's `version` by 1. The `erp_contact_name` is the emergency-response contact, `erp_contact_phone` is the 24-hour contact number, `erp_plan_ref` is the document reference for the plan, and `erp_linked_lepc_district` is the district the plan is filed with. Emergency-response linkage matters beyond record-keeping: as §3.6 explains, a facility cannot file the written follow-up to a release until its `erp_status` is `ACTIVE`.

A facility can be read individually — which reconciles all of its derived fields per §2.6 — and several read-only sub-collections hang off it: its Tier II filings, its permits, its inspections, its compliance cases, and its risk-management plans can each be listed. The compliance-case sub-collection is the only channel through which cascade-created cases (§3.6, §3.9) can be discovered after the fact.

### 3.2. The Global Chemical Catalog and the SDS Repository

Chemicals live in a single global catalog shared by every facility. A `Regulator` adds a chemical with its `cas_number` (the CAS registry number, unique across the catalog), its common `name`, a boolean `is_ehs` marking whether it is an Extremely Hazardous Substance under EPCRA section 302, an `rq_lbs` reportable quantity in pounds, a `hazard_weight` per-1000-pound weighting factor, and a `physical_state` of `SOLID`, `LIQUID`, or `GAS`. A `tpq_lbs` Threshold Planning Quantity in pounds is required when the chemical is an EHS and is ignored otherwise; submitting an EHS chemical without a `tpq_lbs` is malformed and rejected with `ERR_INVALID_REQUEST`. The catalog can be listed (optionally filtered by `is_ehs`) or read one chemical at a time.

Each facility maintains its own repository of safety data sheets. A `FacilityOperator` uploads an SDS for its own facility by supplying the `facility_id`, the `chemical_id` it documents, a `document_ref` storage reference for the sheet, and the manufacturer's `revision_date` printed on it, along with the `expected_facility_version` required by the optimistic-concurrency rule of §2.7. A newly uploaded sheet is created with `status` `ACTIVE`; if an earlier `ACTIVE` sheet already exists for the same `facility_id` and `chemical_id`, that prior sheet is flipped to `SUPERSEDED`, so that at most one active sheet exists per facility-and-chemical pair. Because superseding rewrites the facility's SDS repository, a successful upload increments the facility's `version` by 1. SDS documents can be listed (optionally filtered by `facility_id` and `chemical_id`) or read individually. The presence of an `ACTIVE` SDS for each reportable chemical is a precondition of Tier II submission (§3.4).

### 3.3. Declaring Chemical Inventory: Threshold Determination and Hazard Contribution

A `FacilityOperator` declares what its facility held during a calendar year by creating a chemical-inventory row for its own facility. The declaration names the `facility_id`, the `chemical_id`, the `reporting_year` the amounts describe, the `max_daily_amount_lbs` (the peak amount present on any single day that year), the `average_daily_amount_lbs` (the average amount present per day the chemical was on-site), the `days_on_site` count, and a `storage_type` of `TANK`, `CYLINDER`, `DRUM`, or `BULK`. A new inventory row is created with `status` `ACTIVE`.

At creation the system derives several fields from this row and its chemical. The reporting basis is deliberately a **maximum**, not an average: `reportable_amount_lbs` is set equal to `max_daily_amount_lbs` and is the sole basis for every threshold and Tier II decision. The `average_onsite_lbs` field is set equal to `average_daily_amount_lbs` and is reported for information only — it is never substituted into any threshold, reportability, or fee decision, even though it can differ from the maximum for the same row.

Threshold determination branches on whether the chemical is an EHS. For an EHS chemical, `applicable_threshold_lbs` is the smaller of the chemical's `tpq_lbs` and a cap of 500 pounds; additionally `exceeds_tpq` is set to `true` exactly when `reportable_amount_lbs` reaches or exceeds the chemical's `tpq_lbs` (an inclusive comparison — equal amounts qualify). For a non-EHS chemical, `applicable_threshold_lbs` is a flat 10,000 pounds and `exceeds_tpq` is always `false`. In both cases, `is_reportable` is set to `true` exactly when `reportable_amount_lbs` reaches or exceeds `applicable_threshold_lbs` — again an inclusive lower bound, so an amount exactly equal to the threshold is reportable.

Each inventory row also contributes to its facility's hazard score. The row's `weighted_hazard_contribution` is computed by dividing `max_daily_amount_lbs` by 1,000 pounds, multiplying by the chemical's `hazard_weight`, and rounding that product half up to two decimal places. The facility's `hazard_index` (§2.6) is then the sum of the `weighted_hazard_contribution` values of all of its `ACTIVE` inventory rows — and the rounding order is decisive: each per-row contribution is rounded to two decimals **first**, and only those already-rounded contributions are summed. The system must not sum the raw products and round once at the end. Retired rows are excluded from the sum entirely.

A facility's `is_rmp_required` flag (§2.6) follows directly from these inventories: it is `true` exactly when the facility has at least one `ACTIVE` inventory row whose chemical is an EHS and whose `exceeds_tpq` is `true`.

Inventory rows can be listed (filterable by `facility_id`, `chemical_id`, and `reporting_year`) or read individually. A `FacilityOperator` may retire one of its own facility's rows; retirement is permitted only when the row is `ACTIVE`, and an attempt to retire a row that is already `RETIRED` is rejected with `ERR_INVENTORY_NOT_ACTIVE`. Retiring a row moves its `status` from `ACTIVE` to `RETIRED`, which removes it from the active set: the facility's `hazard_index` therefore decreases by exactly that row's `weighted_hazard_contribution`, and `is_rmp_required` is recomputed to reflect the smaller active set.

### 3.4. The Tier II Filing Lifecycle: Fees, Submission, and Review

A Tier II filing is the annual report a facility owes for a given year, and its lifecycle is cyclic: it moves `DRAFT` → `SUBMITTED` → `UNDER_REVIEW`, and from review it either reaches the terminal `ACCEPTED` state or is sent back to `RETURNED_FOR_REVISION`, from which it re-enters the pipeline. A `FacilityOperator` opens a draft for its own facility by supplying the `facility_id` and the `reporting_year`; the new filing is created in `DRAFT` status. At draft creation two computed fields are set. The `deadline` is fixed at March 1 of the year following the reporting year, at `00:00:00Z` — that is, `submitted_at` after that instant is late. And a **provisional** fee estimate, `provisional_fee_cents`, is computed as a base fee of 5,000 cents plus 2,000 cents for each of the facility's `ACTIVE` inventory rows for that reporting year. The provisional estimate is a flat per-declared-row figure carrying no EHS surcharge and no late penalty.

**Submitting** a filing (which a `FacilityOperator` also performs for its own facility, and which is the same action whether the filing is a first submission from `DRAFT` or a resubmission from `RETURNED_FOR_REVISION`) is guarded by four checks evaluated in this order. First, the filing must currently be in `DRAFT` or `RETURNED_FOR_REVISION`; a submit attempted on any other status is rejected with `ERR_FILING_NOT_SUBMITTABLE`. Second, every chemical that is reportable for the `reporting_year` must have an `ACTIVE` SDS on file at the facility; a missing sheet rejects the submission with `ERR_MISSING_SDS`. Third, there must be at least one reportable inventory row for the `reporting_year`; an empty reportable set is rejected with `ERR_NO_REPORTABLE_CHEMICALS` (HTTP 422). Fourth, the facility must not be under enforcement — if its `compliance_posture` is `ENFORCEMENT`, the submission is rejected with `ERR_FACILITY_UNDER_ENFORCEMENT`.

On a successful submit, the filing advances to `SUBMITTED` and its fee is reassessed. The system first counts the reportable inventory rows for the year into `reportable_chemical_count`, and the subset of those whose chemical is an EHS into `ehs_reportable_count`. The **assessed** fee is then computed from those two counts. Let N be `reportable_chemical_count` and E be `ehs_reportable_count`. The per-chemical component is determined in tiers: if N is 5 or fewer, it is zero (the first 5 chemicals are included in the base fee); if N is between 6 and 25 inclusive, it is 2,000 cents for each chemical beyond the first 5, that is the quantity above 5 multiplied by 2,000 cents; and if N exceeds 25, it is the 20 chemicals from the 6th through the 25th at 2,000 cents each plus each chemical beyond the 25th at 1,000 cents each. An EHS surcharge of 5,000 cents is then added for each EHS-reportable chemical, that is E multiplied by 5,000 cents. The subtotal is the base fee of 5,000 cents plus the per-chemical component plus the EHS surcharge. Finally, if the filing is late, a late penalty equal to the subtotal multiplied by 10 percent, rounded half up to a whole number of cents, is added; if the filing is on time the penalty is zero. The `assessed_fee_cents` is the subtotal plus that penalty. Note the two-step ordering: the subtotal is formed first, and the penalty is a single multiplication applied to that subtotal.

Submitting also stamps `submitted_at` with the current logical clock and sets `is_late` to `true` exactly when `submitted_at` is strictly after the `deadline` (an instant exactly equal to the deadline is on time). The filing now sits in the `SUBMITTED` set, so the facility's `total_outstanding_fee_cents` grows by this filing's assessed-minus-paid amount (§2.8). If the submission is late, a compliance case is opened with `origin` `LATE_FILING`, `severity` `LOW`, and `origin_ref` set to this filing's `id`, after which the facility's posture is recomputed. A resubmission from `RETURNED_FOR_REVISION` runs the same checks and recomputes `assessed_fee_cents`, refreshes `submitted_at` and `is_late`, and reconciles the outstanding ledger in the same way.

Review is a `Regulator`-only action carrying a `decision` of `BEGIN`, `ACCEPT`, or `RETURN`. A `BEGIN` decision moves a filing from `SUBMITTED` to `UNDER_REVIEW` and has no further effect; it is valid only when the filing is `SUBMITTED`, otherwise `ERR_FILING_NOT_REVIEWABLE`. An `ACCEPT` decision moves a filing from `UNDER_REVIEW` to the terminal `ACCEPTED` state; it requires the filing to be `UNDER_REVIEW` (else `ERR_FILING_NOT_REVIEWABLE`) and requires the fee to be fully paid — `fee_paid_cents` must be at least `assessed_fee_cents`, otherwise the acceptance is rejected with `ERR_FEE_UNPAID` (HTTP 402). Once accepted, the filing leaves the set of filings in `SUBMITTED` or `UNDER_REVIEW`, so its now-zero outstanding contribution drops out of the facility's ledger. A `RETURN` decision moves a filing from `UNDER_REVIEW` to `RETURNED_FOR_REVISION` (valid only from `UNDER_REVIEW`, else `ERR_FILING_NOT_REVIEWABLE`); as a compensating action it resets `assessed_fee_cents` back to 0 and increments `revision_count` by 1. Because the returned filing leaves the outstanding set and its assessed amount is zeroed, the facility's `total_outstanding_fee_cents` decreases by the previously-assessed amount — so a submit followed by a return with no payment in between restores the facility's outstanding total to exactly what it was before the submit.

Between submission and acceptance a `FacilityOperator` records payments against its own facility's filing by supplying an `amount_cents`; each payment adds `amount_cents` to the filing's `fee_paid_cents` and reconciles the outstanding ledger.

### 3.5. Chemical Releases, the Enforcement Cascade, and LEPC Notices

When a chemical is released to the environment, the operating facility must report it. A `FacilityOperator` files a release notification for its own facility by supplying the `facility_id`, the `chemical_id` released, the `release_datetime` at which it occurred, the `quantity_released_lbs`, and the `medium` — `AIR`, `WATER`, or `SOIL`. A release may not be reported in the future: the `release_datetime` must be at or before the current logical clock, and a `release_datetime` after the clock is rejected with `ERR_FUTURE_RELEASE` (HTTP 422).

A release notification carries two independent status dimensions that advance separately on the same record. The **reporting** dimension begins at `PENDING_VERBAL` and the **remediation** dimension begins at `ONGOING`. At creation the system also determines whether the release is reportable to emergency planners: `exceeds_rq` is set to `true` exactly when `quantity_released_lbs` reaches or exceeds the chemical's `rq_lbs` (an inclusive comparison — an amount exactly equal to the reportable quantity qualifies), and `requires_lepc` is set equal to `exceeds_rq`, since an RQ-exceeding release is precisely the kind that must be reported to the LEPC and SERC.

An RQ-exceeding release sets off a three-step enforcement cascade in a single atomic operation. First, a compliance case is opened with `origin` `RELEASE_RQ_EXCEEDED`, `severity` `HIGH`, and `origin_ref` set to this release's `id`, and the release's `origin_case_opened` flag is set to `true`. Second, because that new case is a `HIGH`-severity case, the facility's `compliance_posture` is forced to `ENFORCEMENT`. Third, because the facility has entered `ENFORCEMENT`, every one of its permits currently in `ACTIVE` status is moved to `SUSPENDED`. A release that does not exceed its RQ opens no case, leaves `origin_case_opened` as `false`, and disturbs neither posture nor permits.

The reporting dimension is advanced by a `FacilityOperator` supplying a `stage`. A `stage` of `VERBAL` moves `reporting_status` from `PENDING_VERBAL` to `VERBAL_GIVEN`; it is valid only when `reporting_status` is `PENDING_VERBAL`, otherwise `ERR_RELEASE_INVALID_STAGE`. A `stage` of `WRITTEN` moves `reporting_status` from `VERBAL_GIVEN` to `WRITTEN_FILED`; it requires `reporting_status` to be `VERBAL_GIVEN` (else `ERR_RELEASE_INVALID_STAGE`) and additionally requires the facility to have an emergency-response plan on file — its `erp_status` must be `ACTIVE`, and a written follow-up attempted while `erp_status` is `NONE` is rejected with `ERR_NO_ERP_LINKAGE`. The remediation dimension is advanced by a `FacilityOperator` supplying a `to` target. A `to` of `CONTAINED` moves `remediation_status` from `ONGOING` to `CONTAINED` (valid only from `ONGOING`, else `ERR_RELEASE_INVALID_STAGE`), and a `to` of `CLOSED` moves it from `CONTAINED` to `CLOSED` (valid only from `CONTAINED`, else `ERR_RELEASE_INVALID_STAGE`). Because the two dimensions are independent, remediation can progress while reporting is still pending, and vice versa.

Releases can be listed (filterable by `facility_id` and `chemical_id`) or read individually. For a release that requires LEPC involvement, a `FacilityOperator` records the outbound notices by supplying the `release_id`, a `notice_type` of `VERBAL` or `WRITTEN`, and a `recipient` of `LEPC`, `SERC`, or `NRC`. Each recorded notice is stamped with a `sent_at` taken from the logical clock and starts with `acknowledged` set to `false`. A `LEPCCoordinator` — and only a `LEPCCoordinator` — acknowledges a notice, which sets its `acknowledged` flag to `true`. The notices attached to a given release can be listed.

### 3.6. Permits, Inspections, and Compliance Cases

A `Regulator` issues a permit to a facility by supplying the `facility_id`, a `permit_type` of `OPERATING`, `STORAGE`, or `AIR`, an `issued_date`, an `expiry_date`, and a `fee_cents` issuance fee. A new permit is created in `ACTIVE` status. Two guards apply. Fiscally, a permit may be issued only when the facility owes nothing: if the facility's `total_outstanding_fee_cents` is greater than zero, issuance is blocked with `ERR_OUTSTANDING_FEES` (HTTP 402). Temporally, the permit's validity interval runs inclusively from `issued_date` through `expiry_date`, and it may not overlap the interval of an existing permit of the same `permit_type` on the same facility; an overlap is rejected with `ERR_PERMIT_PERIOD_OVERLAP`. A permit's `status` is otherwise driven entirely by the system: it moves from `ACTIVE` to `SUSPENDED` when the facility enters `ENFORCEMENT` (§3.5) and back from `SUSPENDED` to `ACTIVE` when the facility later leaves enforcement, and it becomes `EXPIRED` once the logical clock passes its `expiry_date`, evaluated when the permit is read or accessed while still `ACTIVE`.

A `Regulator` schedules an inspection by supplying the `facility_id`, an `inspector_id` (an opaque inspector operator identifier, not an entity reference), and a `scheduled_date`. A new inspection is created in `SCHEDULED` status. To prevent double-booking, an inspection may not be scheduled within 24 hours of another inspection already booked for the same `inspector_id`; a conflict is rejected with `ERR_INSPECTOR_DOUBLE_BOOKED`. A regulator begins a scheduled inspection, moving it from `SCHEDULED` to `IN_PROGRESS` (valid only when the inspection is `SCHEDULED`, else `ERR_INSPECTION_NOT_SCHEDULED`). A regulator then completes an in-progress inspection by supplying a `result`; completion is valid only when the inspection is `IN_PROGRESS`, otherwise `ERR_INSPECTION_NOT_IN_PROGRESS`. The completion forks on the result. A `result` of `PASS` moves the inspection to `PASSED`, sets its `result` to `PASS`, and sets `findings_count` to 0. A `result` of `FAIL` moves the inspection to `FAILED`, sets its `result` to `FAIL`, and records `findings_count` from the supplied `findings_count` in the payload; it then opens a compliance case with `origin` `INSPECTION_FAILED`, `severity` `MEDIUM`, and `origin_ref` set to this inspection's `id`, and forces the facility's `compliance_posture` to `DEFICIENT` unless the facility is already in `ENFORCEMENT` (a `HIGH`-severity enforcement posture is never downgraded by a merely `MEDIUM` case).

Compliance cases are the enforcement backbone, and most arise automatically: an RQ-exceeding release opens a `HIGH` case with `origin` `RELEASE_RQ_EXCEEDED`, a failed inspection opens a `MEDIUM` case with `origin` `INSPECTION_FAILED`, and a late filing opens a `LOW` case with `origin` `LATE_FILING`. A `Regulator` may also open a case manually against a facility by supplying the `facility_id` and, optionally, a `severity`; a manually opened case has `origin` `MANUAL`, starts in `OPEN` status, defaults to `LOW` severity when none is supplied, and triggers a posture recomputation. Each case carries an `origin_ref` pointing at the record that triggered it (a release, an inspection, or a filing, as applicable) and a `penalty_cents` that starts at 0. A case advances `OPEN` → `UNDER_REVIEW` → `RESOLVED`. A regulator moves a case into review, valid only from `OPEN` (else `ERR_CASE_NOT_OPEN`). A regulator resolves a case from `UNDER_REVIEW` (else `ERR_CASE_NOT_UNDER_REVIEW`), optionally supplying a `penalty_cents` recorded on the case; resolution is additionally gated on the facility's most recent inspection having `PASSED` — if the latest inspection is anything else, resolution is blocked with `ERR_UNRESOLVED_INSPECTION`. Resolving a case recomputes the facility's `open_case_count` and `compliance_posture`; and if that recomputation takes the facility out of `ENFORCEMENT`, every one of its `SUSPENDED` permits is reinstated to `ACTIVE` as a compensating action mirroring the suspension cascade of §3.5.

### 3.7. Risk-Management-Plan Tracking

Facilities that handle certain regulated substances must keep a Risk Management Plan (RMP) current. A `FacilityOperator` submits its own facility's plan by supplying the `facility_id`, a `program_level` of 1, 2, or 3, and the `submitted_date`. The plan is created in `ACTIVE` status, and its `next_due_date` is computed as the `submitted_date` advanced by five years.

An RMP's lifecycle is cyclic and driven by the logical clock relative to its `next_due_date`. While the clock is comfortably before the due date the plan stays `ACTIVE`. Once the clock comes within 90 days of the `next_due_date`, the plan enters `DUE`. Once the clock passes the `next_due_date` outright, the plan becomes `OVERDUE`. A `FacilityOperator` resubmits its own facility's plan — from either `DUE` or `OVERDUE` — by supplying a fresh `submitted_date`; resubmission returns the plan to `ACTIVE`, records the new `submitted_date`, and recomputes `next_due_date` as that new date plus five years. A facility's risk-management plans can be listed from its sub-collection (§3.1).

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201; endpoints that modify or transition an existing resource, and all read endpoints, return HTTP 200. Request and response bodies are governed by the narratives in §3 and the envelope of §2.2; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | `/_clock/set_current_utc` | Set the server logical clock | Regulator |
| POST | `/epcra/facilities` | Register a regulated facility | Regulator |
| GET | `/epcra/facilities` | List facilities | Regulator, FacilityOperator, LEPCCoordinator |
| GET | `/epcra/facilities/{id}` | Get a facility (derived fields reconciled on read) | Regulator, FacilityOperator, LEPCCoordinator |
| POST | `/epcra/facilities/{id}/emergency-response-plan` | Link / update the facility emergency-response plan | FacilityOperator |
| GET | `/epcra/facilities/{id}/tier-ii-filings` | List a facility's Tier II filings | Regulator, FacilityOperator, LEPCCoordinator |
| GET | `/epcra/facilities/{id}/permits` | List a facility's permits | Regulator, FacilityOperator, LEPCCoordinator |
| GET | `/epcra/facilities/{id}/inspections` | List a facility's inspections | Regulator, FacilityOperator, LEPCCoordinator |
| GET | `/epcra/facilities/{id}/compliance-cases` | List a facility's compliance cases | Regulator, FacilityOperator, LEPCCoordinator |
| GET | `/epcra/facilities/{id}/risk-management-plans` | List a facility's risk-management plans | Regulator, FacilityOperator, LEPCCoordinator |
| POST | `/epcra/chemicals` | Add a chemical to the global catalog | Regulator |
| GET | `/epcra/chemicals` | List catalog chemicals | Regulator, FacilityOperator, LEPCCoordinator |
| GET | `/epcra/chemicals/{id}` | Get a catalog chemical | Regulator, FacilityOperator, LEPCCoordinator |
| POST | `/epcra/chemical-inventories` | Declare a facility chemical inventory for a reporting year | FacilityOperator |
| GET | `/epcra/chemical-inventories` | List inventories (filter by facility, chemical, year) | Regulator, FacilityOperator, LEPCCoordinator |
| GET | `/epcra/chemical-inventories/{id}` | Get an inventory row | Regulator, FacilityOperator, LEPCCoordinator |
| POST | `/epcra/chemical-inventories/{id}/retire` | Retire an inventory row | FacilityOperator |
| POST | `/epcra/tier-ii-filings` | Open a Tier II filing draft | FacilityOperator |
| POST | `/epcra/tier-ii-filings/{id}/submit` | Submit or resubmit a Tier II filing | FacilityOperator |
| POST | `/epcra/tier-ii-filings/{id}/review` | Regulator review decision: BEGIN, ACCEPT, or RETURN | Regulator |
| POST | `/epcra/tier-ii-filings/{id}/pay` | Record a fee payment against a filing | FacilityOperator |
| POST | `/epcra/sds` | Upload an SDS (supersedes prior active sheet; OCC on facility version) | FacilityOperator |
| GET | `/epcra/sds` | List SDS documents (filter by facility, chemical) | Regulator, FacilityOperator, LEPCCoordinator |
| GET | `/epcra/sds/{id}` | Get an SDS document | Regulator, FacilityOperator, LEPCCoordinator |
| POST | `/epcra/release-notifications` | Report a chemical release | FacilityOperator |
| GET | `/epcra/release-notifications` | List releases (filter by facility, chemical) | Regulator, FacilityOperator, LEPCCoordinator |
| GET | `/epcra/release-notifications/{id}` | Get a release notification | Regulator, FacilityOperator, LEPCCoordinator |
| POST | `/epcra/release-notifications/{id}/report` | Advance the reporting dimension (VERBAL then WRITTEN) | FacilityOperator |
| POST | `/epcra/release-notifications/{id}/remediation` | Advance the remediation dimension (CONTAINED then CLOSED) | FacilityOperator |
| GET | `/epcra/release-notifications/{id}/lepc-notices` | List LEPC/SERC/NRC notices for a release | Regulator, FacilityOperator, LEPCCoordinator |
| POST | `/epcra/lepc-notices` | Record a LEPC/SERC/NRC notice for a release | FacilityOperator |
| POST | `/epcra/lepc-notices/{id}/acknowledge` | Acknowledge receipt of a notice | LEPCCoordinator |
| POST | `/epcra/permits` | Issue a facility permit | Regulator |
| POST | `/epcra/inspections` | Schedule a facility inspection | Regulator |
| POST | `/epcra/inspections/{id}/start` | Begin a scheduled inspection | Regulator |
| POST | `/epcra/inspections/{id}/complete` | Complete an inspection with PASS or FAIL | Regulator |
| POST | `/epcra/compliance-cases` | Open a compliance case manually | Regulator |
| POST | `/epcra/compliance-cases/{id}/review` | Move a case into review | Regulator |
| POST | `/epcra/compliance-cases/{id}/resolve` | Resolve a case (requires latest inspection PASSED) | Regulator |
| POST | `/epcra/risk-management-plans` | Submit a facility RMP | FacilityOperator |
| POST | `/epcra/risk-management-plans/{id}/resubmit` | Resubmit an RMP (returns DUE/OVERDUE to ACTIVE) | FacilityOperator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|------------------|
| `ERR_MISSING_AUTH_HEADER` | 400 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_FACILITY_NOT_FOUND` | 404 |
| `ERR_CHEMICAL_NOT_FOUND` | 404 |
| `ERR_INVENTORY_NOT_FOUND` | 404 |
| `ERR_FILING_NOT_FOUND` | 404 |
| `ERR_SDS_NOT_FOUND` | 404 |
| `ERR_RELEASE_NOT_FOUND` | 404 |
| `ERR_LEPC_NOTICE_NOT_FOUND` | 404 |
| `ERR_PERMIT_NOT_FOUND` | 404 |
| `ERR_INSPECTION_NOT_FOUND` | 404 |
| `ERR_CASE_NOT_FOUND` | 404 |
| `ERR_RMP_NOT_FOUND` | 404 |
| `ERR_STALE_FACILITY_VERSION` | 412 |
| `ERR_FILING_NOT_SUBMITTABLE` | 409 |
| `ERR_FILING_NOT_REVIEWABLE` | 409 |
| `ERR_INSPECTION_NOT_SCHEDULED` | 409 |
| `ERR_INSPECTION_NOT_IN_PROGRESS` | 409 |
| `ERR_CASE_NOT_OPEN` | 409 |
| `ERR_CASE_NOT_UNDER_REVIEW` | 409 |
| `ERR_RELEASE_INVALID_STAGE` | 409 |
| `ERR_INVENTORY_NOT_ACTIVE` | 409 |
| `ERR_MISSING_SDS` | 409 |
| `ERR_NO_REPORTABLE_CHEMICALS` | 422 |
| `ERR_PERMIT_PERIOD_OVERLAP` | 409 |
| `ERR_INSPECTOR_DOUBLE_BOOKED` | 409 |
| `ERR_FUTURE_RELEASE` | 422 |
| `ERR_NO_ERP_LINKAGE` | 409 |
| `ERR_FACILITY_UNDER_ENFORCEMENT` | 409 |
| `ERR_UNRESOLVED_INSPECTION` | 409 |
| `ERR_OUTSTANDING_FEES` | 402 |
| `ERR_FEE_UNPAID` | 402 |
