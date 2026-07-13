# Rabies Animal Bite Case Management API — Product Requirements Document

## 1. Introduction

Local health departments carry statutory responsibility for every reported animal bite: the person exposed must be triaged for rabies risk and, where warranted, started on post-exposure prophylaxis; the biting animal must be traced, confined, and observed or laboratory-tested; and non-compliant owners must be cited and, when needed, referred to animal control. Today much of this coordination happens across disconnected spreadsheets and paper confinement orders, which makes it hard to prove that a 10-day observation window actually elapsed, that a lab-positive result triggered the right public-health escalation, or that a fine was calculated and collected correctly.

This API unifies that workflow into a single case-management backbone. It captures a bite report at intake, scores the victim's rabies-exposure risk and derives a prophylaxis recommendation, drives the biting animal through quarantine or specimen submission, records laboratory results, and rolls confirmed-positive findings up into a per-region surveillance picture that can raise an outbreak alert. In parallel it enforces owner accountability — issuing citations, tracking outstanding fines, and segregating who may issue a citation from who may resolve a contested one. Every deadline, expiry, and observation window is evaluated against a server-controlled logical clock so that the same case data always produces the same, reproducible determination.

The remainder of this document defines the global contracts every endpoint obeys (Section 2), the domain workflows and the business rules scattered through them (Section 3), the full endpoint surface (Section 4), and the catalogue of error identifiers (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or presenting an `X-User-Role` that is not one of the recognized roles, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes six roles, spelled exactly as follows: `IntakeOfficer`, `Epidemiologist`, `Veterinarian`, `AnimalControlOfficer`, `Owner`, and `HealthDeptAdmin`. Each of the first four is a distinct operational staff role that owns a specific slice of the workflow — intake and reporting, victim risk follow-up, quarantine and laboratory handling, and field enforcement respectively. `HealthDeptAdmin` is an operational superset that may perform every business operation in addition to facility setup, region setup, and control of the logical clock. A deliberate segregation of duties keeps citation **issuance** (an `AnimalControlOfficer` capability) separate from citation-hearing **resolution** (an `Epidemiologist` capability), so the same person cannot both write and adjudicate a fine.

For the five staff roles — `IntakeOfficer`, `Epidemiologist`, `Veterinarian`, `AnimalControlOfficer`, and `HealthDeptAdmin` — `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server does not compare it to any entity's `id`. The `Owner` role is different: when `X-User-Role` is `Owner`, `X-User-ID` is the `id` of the acting `Owner` entity. Ownership checks on any resource that references an owner compare that resource's owner foreign key to `X-User-ID` — concretely, an `Owner` may act on a `Citation` only when the citation's `owner_id` equals the caller's `X-User-ID`, and may read only citations they own.

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

---

### 2.3. Pagination and Filtering

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, may be no smaller than 1, and no larger than 100. The `offset` parameter counts how many items to skip and defaults to 0. Every list response echoes `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object.

Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order (oldest first).

Several list endpoints also accept domain filters supplied as query parameters. Animals may be filtered by `owner_id` or by `status`. Bite cases may be filtered by `animal_id`, `status`, or `region_code`. Quarantine orders may be filtered by `case_id`, `animal_id`, `facility_id`, or `status`. Specimens may be filtered by `case_id` or `animal_id`. Citations may be filtered by `owner_id`, `case_id`, or `status`. These filters implement foreign-key reverse-reachability — for example, filtering animals by `owner_id` returns exactly the animals owned by that owner.

### 2.4. Common Resource Properties

Every resource in this system is a first-class, top-level entity and carries a common set of system-managed fields:

- `id` — a server-minted UUID, with no type prefix, unique across the system.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp recording the most recent modification; it is refreshed on every mutation of the resource.
- `version` — an integer that starts at its initial value and increments by one on every mutation. It underpins optimistic concurrency control (Section 2.6).

All ten resource types (owners, animals, bite cases, quarantine facilities, quarantine orders, specimens, PEP recommendations, citations, surveillance regions, and wildlife-exposure reports) expose all four of these fields. Whenever a derived or computed field on a resource changes — for instance an owner's `compliance_status`, a facility's `current_occupancy`, or a case's `risk_level` — that change is itself a mutation that refreshes `updated_at` and increments `version` on the owning resource.

### 2.5. The Logical Clock and Temporal Determinism

All time-sensitive rules — the 10-day quarantine window, citation due dates, specimen collection instants, and quarantine-window overlap — are evaluated against a server-controlled **logical clock**, never against wall-clock time. On startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any client sets it the clock stays at that default and never falls back to the machine's real time. A `HealthDeptAdmin` may advance the clock by supplying a target instant in the `to_iso8601` field of the clock-setting capability; from then on all deadline, expiry, and window comparisons read the clock's current value. This makes every temporal determination fully reproducible from the sequence of requests.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control against their parent `BiteCase`: issuing a quarantine order for a case, and creating (superseding) a PEP recommendation for a case. Both operations require a non-optional `expected_bite_case_version` field in the request body, carrying the case `version` the client last observed.

When the submitted `expected_bite_case_version` does not equal the target case's current `version`, the request is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412). A mismatch means the case has advanced since the client last read it — for example, a lab-positive cascade forced the prior recommendation, an earlier revision already superseded it, or an intervening capture/identification of an at-large animal bumped the case — so the client's view is stale and the write must be retried against the fresh version. Endpoints other than these two do not accept a version field and perform no such check.

### 2.7. Monetary Amounts, Precision, and Rounding

All monetary amounts in this system — fines, boarding costs, and prophylaxis costs — are stored and returned as integer counts of cents. Fields such as `outstanding_fines_cents`, `daily_boarding_cents`, `boarding_cost_cents`, `base_fine_cents`, `total_fine_cents`, `projected_cost_cents`, `final_cost_cents`, and `payment_amount_cents` are therefore whole integers.

Where a calculation introduces a fractional cent — specifically the citation surcharge described in Section 3.7 — rounding is performed with the **round half up** method to a whole cent, and the rounding is applied **per violation line before the lines are summed**, never after. Counts of whole days for boarding are obtained by taking the floor of the elapsed 24-hour periods, with a floor of one day. These precision rules are restated in the workflow sections where the calculations live.

### 2.8. Cross-Entity State Consistency and Cascades

Many operations in this domain mutate more than one resource in a single atomic step, and every such cascade must be applied in full. When a quarantine order reaches a terminal state, its animal, its bite case, and (for facility orders) its facility occupancy all move together; when a laboratory result is reported, the specimen, the case, any open PEP recommendation, and the relevant surveillance region are all reconciled together. Each affected resource is independently mutated, meaning its `updated_at` is refreshed and its `version` is incremented. The specific cascades — which resources move, to which states, and with which side effects — are documented alongside the workflow that triggers them in Section 3, and implementers must treat those secondary effects as mandatory rather than optional.

### 2.9. Resource Existence and Left-to-Right Path Validation

Requests are validated for resource existence before any business rule runs. For endpoints whose URL carries one or more resource identifiers, those identifiers are validated in left-to-right order, and the first identifier that does not resolve to an existing resource produces that resource's specific not-found error — for example a missing owner yields `ERR_OWNER_NOT_FOUND`, a missing animal `ERR_ANIMAL_NOT_FOUND`, a missing bite case `ERR_CASE_NOT_FOUND`, a missing facility `ERR_FACILITY_NOT_FOUND`, a missing quarantine order `ERR_QUARANTINE_ORDER_NOT_FOUND`, a missing specimen `ERR_SPECIMEN_NOT_FOUND`, a missing PEP recommendation `ERR_PEP_NOT_FOUND`, a missing citation `ERR_CITATION_NOT_FOUND`, and a missing surveillance region `ERR_REGION_NOT_FOUND`. The same not-found errors apply when a creation body carries a foreign key — `owner_id`, `animal_id`, `case_id`, `facility_id`, or `region_id` — that does not reference an existing row.

### 2.10. Validation Precedence

When several checks guard a single operation, they are evaluated in a fixed precedence so that the returned `error_id` is deterministic. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then existence of path-referenced resources, then existence of body foreign keys, then request well-formedness — required fields present, enum values legal, `victim_age` not negative, and `violations` non-empty — which otherwise yields `ERR_INVALID_REQUEST`. Domain-specific checks follow in the order called out in each workflow below. Two orderings are pinned explicitly because they matter for testing: on quarantine-order issuance the facility-shape check (`ERR_FACILITY_REQUIRED`) is evaluated **before** the concurrency check (`ERR_STALE_CASE_VERSION`), so a malformed body never masks a version conflict; and on citation payment the state check precedes the ownership check, which in turn precedes the payment-amount check.

## 3. Business Logic & Workflows

### 3.1. Bite Report Intake, Owner and Animal Registration, and Risk Scoring

The workflow begins when an owner or animal is registered and a bite is reported. An `IntakeOfficer` (or `HealthDeptAdmin`) registers an **Owner** by supplying the owner's `full_name` and `phone`, optionally their `address` and `license_number`; when a license number is not supplied it is stored as null, marking an unlicensed party. A newly registered owner starts `COMPLIANT` with `outstanding_fines_cents` of zero.

Animals are recorded by an `IntakeOfficer`, an `AnimalControlOfficer`, or a `HealthDeptAdmin`. An **Animal** is created with a `species` (one of `DOG`, `CAT`, `FERRET`, `BAT`, `RACCOON`, `SKUNK`, `FOX`, `COYOTE`, `LIVESTOCK`, or `OTHER`) and an `animal_class` (one of `DOMESTIC`, `WILD`, or `STRAY`). Optionally the payload sets `owner_id` (null for strays and unidentified animals), `identified` (defaulting to true; false marks an at-large or unknown animal), `vaccination_status` (one of `CURRENT`, `EXPIRED`, `UNKNOWN`, or `NONE`, defaulting to `UNKNOWN`), and `rabies_vaccine_expiry` (the expiry instant of a current vaccination, null when unknown or none). A new animal begins in status `REPORTED`, with `disposition` `NONE` and `control_status` `NONE`.

A bite report is intaked by an `IntakeOfficer` or `HealthDeptAdmin` as a **BiteCase**. The intake payload carries the `region_code` of the incident, the `incident_datetime` at which the exposure occurred, the `exposure_type` (one of `BITE`, `SCRATCH`, or `SALIVA_MUCOSAL`), the `body_site` (one of `HEAD_NECK`, `HAND`, `ARM`, `TORSO`, `LEG`, or `FOOT`), the `wound_category` (WHO category, one of `CATEGORY_I` for touching or feeding intact skin, `CATEGORY_II` for minor scratches or abrasions without bleeding, or `CATEGORY_III` for a transdermal bite/scratch or mucosal contact), the `victim_name`, the `victim_age` in whole years (which must be zero or greater), optionally `victim_prior_vaccinated` (defaulting to false), and optionally the `animal_id` of the biting animal (null when the animal is unidentified or not yet captured). Intake mints a human-readable `case_number` (for example `RB-000001`), places the case in status `OPEN`, and immediately computes the case's `risk_level` and `pep_indication`.

The **risk_level** determination reads the single bite case together with its referenced animal, if any, and is evaluated as an ordered sequence of clauses where the first matching clause decides the outcome. First, if the `wound_category` is `CATEGORY_I`, the `risk_level` is `NONE`. Otherwise, if there is no `animal_id`, or the referenced animal's `identified` flag is false, or that animal's status is `AT_LARGE`, the `risk_level` is `HIGH` — an animal that cannot be produced for observation is treated as the worst case. Otherwise, if the referenced animal's `animal_class` is `WILD` and its `species` is one of the high-risk reservoir species — `BAT`, `RACCOON`, `SKUNK`, `FOX`, or `COYOTE` — the `risk_level` is `HIGH`. Otherwise, if the animal's `species` is one of the observable domestic species — `DOG`, `CAT`, or `FERRET` — then a `vaccination_status` of `CURRENT` yields `risk_level` `LOW` while any other vaccination status yields `MODERATE`. In every remaining case the `risk_level` is `MODERATE`.

The `pep_indication` is derived directly from the resulting `risk_level` by a fixed mapping: `NONE` maps to `NOT_INDICATED`, `LOW` maps to `DEFER`, `MODERATE` maps to `INITIATE`, and `HIGH` maps to `INITIATE`. Both `risk_level` and `pep_indication` are stored on the case at intake. The bite case's own lifecycle status advances from `OPEN` into either the observation branch (`OBSERVATION_PENDING`) or the laboratory branch (`LAB_PENDING`) as later sections describe, and ultimately to `CONFIRMED_RABID`, `CLEARED`, and finally the terminal `CLOSED`.

### 3.2. Animal Identification, Capture, and Disposition

The biting animal must be traced through the field-enforcement workflow, which is chiefly the province of the `AnimalControlOfficer` (with `HealthDeptAdmin` able to act throughout, and a `Veterinarian` also able to record dispositions).

When an unidentified animal cannot be produced, an officer records it as having escaped: for an animal still in `REPORTED` whose `identified` flag is false, submitting an escape record — the `disposition` field omitted and the `escaped` flag set to true — advances the animal from `REPORTED` to `AT_LARGE`, leaving `control_status` at `NONE` until a dispatch is later requested. An animal that is `AT_LARGE` can subsequently be brought in by an animal-control capture, which advances it from `AT_LARGE` to `CAPTURED` and sets its `control_status` to `CAPTURED`.

Recording a final disposition on an animal that is in `REPORTED` or `CAPTURED` uses the same disposition capability with the `disposition` field populated: a value of `EUTHANIZED` moves the animal to `EUTHANIZED`, and a value of `DECEASED` moves it to `DECEASED`. In both cases the animal's `disposition` field is set to match and the animal becomes eligible for specimen submission. The animal's `status`, `disposition`, and `control_status` are the three system-managed enums that track this progress; `status` ranges over `REPORTED`, `AT_LARGE`, `CAPTURED`, `UNDER_OBSERVATION`, `RELEASED`, `DECEASED`, and `EUTHANIZED`, while `disposition` ranges over `NONE`, `RELEASED`, `DECEASED`, and `EUTHANIZED`, and `control_status` over `NONE`, `DISPATCH_REQUESTED`, and `CAPTURED`. The remaining two animal transitions — into and out of `UNDER_OBSERVATION` — are driven by the quarantine workflow described next.

### 3.3. Issuing a Quarantine Order and Beginning Confinement

Confinement is set up as a **QuarantineFacility** and then exercised through a **QuarantineOrder**. A `HealthDeptAdmin` creates a facility by supplying its `name`, its `facility_type` (`SHELTER` or `VET_CLINIC`), its `capacity` (the maximum number of animals in overlapping active quarantine, at least 1), and its `daily_boarding_cents` (the cost per whole confinement day, zero or greater). A facility begins with `current_occupancy` of zero, which is the count of its quarantine orders currently `ACTIVE`; occupancy is recomputed when an order activates and on every terminal transition of one of its orders.

A `Veterinarian`, `AnimalControlOfficer`, or `HealthDeptAdmin` issues a quarantine order against an `OPEN` bite case. The order body carries the `expected_bite_case_version` (the concurrency guard of Section 2.6), the `animal_id` of the animal to confine, the `order_type` (`HOME_CONFINEMENT` or `FACILITY`), optionally a `facility_id`, and optionally a `start_date`; when `start_date` is omitted it defaults to the logical clock's current value. A `FACILITY` order must supply a `facility_id`, and a `HOME_CONFINEMENT` order must not supply one; violating this shape is rejected with `ERR_FACILITY_REQUIRED`, and — as noted in Section 2.10 — this shape check runs before the concurrency check so that a malformed body cannot hide a version conflict. The order also requires that the referenced animal exists and is neither `DECEASED` nor `EUTHANIZED`, and that the case is still `OPEN`.

The order's ten-day observation window is the half-open interval that begins at `start_date` and ends at the computed `scheduled_end_date`, which is exactly `start_date` plus ten days. Two temporal constraints protect that window. First, the new order's window must not overlap any existing `ACTIVE` order for the same animal; an order whose window overlaps such an order is rejected with `ERR_ANIMAL_QUARANTINE_OVERLAP`, though adjacency where the new order's `start_date` equals the old order's `scheduled_end_date` is permitted. Second, for `FACILITY` orders the facility's capacity must hold at every instant of the new window: if at any instant within `[start_date, scheduled_end_date)` the count of `ACTIVE` facility orders whose windows include that instant would rise above the facility's `capacity`, the order is rejected with `ERR_FACILITY_AT_CAPACITY`.

A successful issuance creates the `QuarantineOrder` in status `ACTIVE`, sets its `actual_release_date` to null and its `observation_outcome` to `PENDING`, moves the referenced animal from `REPORTED` or `CAPTURED` to `UNDER_OBSERVATION`, moves the bite case from `OPEN` to `OBSERVATION_PENDING`, and increments the bite case's `version` by one. For a facility order the facility's `current_occupancy` is increased by one. The order's `case_id` and `animal_id` identify the case and confined animal, and its `facility_id` is null for home confinement. Because issuance bumps the case version, a later re-issue (for instance after an at-large animal is finally captured and identified) must carry the updated `expected_bite_case_version` or be rejected as stale per Section 2.6.

The order's **boarding_cost_cents** follows a dual-variant rule. For `HOME_CONFINEMENT` the boarding cost is always zero. For a `FACILITY` order it is `billable_days` multiplied by the facility's `daily_boarding_cents`. While the order is `ACTIVE` the estimated variant applies and `billable_days` is fixed at the full ten-day window. Once the order is terminal the actual variant applies: `billable_days` is the number of whole 24-hour days from `start_date` to `actual_release_date`, taken as a floor, but never fewer than one day. The estimated and actual variants diverge whenever an order ends early through breach or conversion rather than running the full ten days.

### 3.4. Resolving a Quarantine: Completion, Breach, and Conversion

An `ACTIVE` quarantine order resolves in exactly one of three ways, and each drives its animal and bite case in lockstep.

A `Veterinarian` (or `HealthDeptAdmin`) **completes** a quarantine to release a healthy animal, optionally supplying the `observation_outcome` (one of `PENDING`, `HEALTHY`, `SYMPTOMATIC`, or `DECEASED`). Completion enforces three checks, evaluated in this order: first the safety check — an order may not be completed when the observation outcome is `SYMPTOMATIC` or `DECEASED`, in which case it is rejected with `ERR_ANIMAL_SYMPTOMATIC` and the animal must instead be converted to a specimen; then the state check — the order must currently be `ACTIVE`, otherwise `ERR_INVALID_STATE`; then the temporal check — the logical clock must be at or after the order's `scheduled_end_date`, meaning the full ten-day window has elapsed (the boundary is inclusive), otherwise `ERR_QUARANTINE_NOT_ELAPSED`. On success the order moves from `ACTIVE` to `COMPLETED`, its `actual_release_date` is set to the clock's current value, its `boarding_cost_cents` is recomputed to the actual variant, the animal moves from `UNDER_OBSERVATION` to `RELEASED` with its `disposition` set to `RELEASED`, the bite case moves from `OBSERVATION_PENDING` to `CLEARED`, and for a facility order the facility's `current_occupancy` is decreased by one. Any `DEFER` or `RECOMMENDED` PEP recommendation on the case remains eligible for later discontinuation.

An `AnimalControlOfficer` (or `HealthDeptAdmin`) records a **breach** when an animal escapes confinement; this is permitted while the order is `ACTIVE`. A breach moves the order from `ACTIVE` to `BREACHED`, sets `actual_release_date` to the clock's current value, recomputes `boarding_cost_cents` to the actual variant, and, for a facility order, decreases the facility's `current_occupancy` by one. A breach also triggers an enforcement cascade: the system auto-issues a `Citation` to the order's owner carrying the single violation `QUARANTINE_BREACH`; that citation increases the owner's `outstanding_fines_cents` and drives the owner's `compliance_status` to `DELINQUENT`; and the animal's `control_status` is set to `DISPATCH_REQUESTED` to trigger animal-control seizure.

A `Veterinarian` (or `HealthDeptAdmin`) **converts** a quarantine to specimen submission when the confined animal became symptomatic or died during observation; this too requires the order to be `ACTIVE` and carries a `collected_datetime` and a specimen `condition`. Conversion moves the order from `ACTIVE` to `CONVERTED_TO_SPECIMEN`, sets `actual_release_date` to the clock's current value, recomputes `boarding_cost_cents` to the actual variant, moves the animal from `UNDER_OBSERVATION` to `DECEASED`, moves the bite case from `OBSERVATION_PENDING` to `LAB_PENDING`, creates a new `Specimen` in `SUBMITTED` for that animal, and, for a facility order, decreases the facility's `current_occupancy` by one.

### 3.5. Specimen Submission and Laboratory Results

The laboratory branch handles brain-specimen testing of a deceased or euthanized animal. A `Veterinarian` (or `HealthDeptAdmin`) submits a **Specimen** against an `OPEN` bite case, supplying the `animal_id`, the `collected_datetime`, and the `condition` (one of `SATISFACTORY`, `AUTOLYZED`, or `UNSATISFACTORY`). Submission requires the referenced animal to be `DECEASED` or `EUTHANIZED`; otherwise it is rejected with `ERR_ANIMAL_NOT_DECEASED`. The specimen's `condition` determines its fate at creation, and these two sibling outcomes carry equal weight. A `SATISFACTORY` specimen is persisted in status `SUBMITTED` and drives the bite case from `OPEN` to `LAB_PENDING`. An `AUTOLYZED` or `UNSATISFACTORY` specimen is instead persisted directly in the terminal status `REJECTED`: it can never be tested, no result can be reported on it, and the case remains in `LAB_PENDING` awaiting a fresh specimen. A specimen only ever reaches `REJECTED` at creation time; a specimen already `SUBMITTED` is never rejected afterward. Every specimen also carries `test_method` (null until a result is reported, otherwise `DFA` or `RT_PCR`), `result` (`PENDING` until reported, thereafter `POSITIVE`, `NEGATIVE`, or `INDETERMINATE`), and `reported_datetime` (null while pending).

A `Veterinarian` (or `HealthDeptAdmin`) reports a laboratory result on a `SUBMITTED` specimen, supplying the `test_method` and the `result`; if the specimen is not `SUBMITTED` the request is rejected with `ERR_INVALID_STATE`. Reporting moves the specimen from `SUBMITTED` to `RESULTED`, recording the `result`, `test_method`, and a `reported_datetime` of the clock's current value. The reported result then drives the case's laboratory branch. A `NEGATIVE` result moves the case from `LAB_PENDING` to `CLEARED`, and any active `INITIATED` PEP recommendation on the case becomes eligible for discontinuation because the animal is cleared. An `INDETERMINATE` result leaves the case in `LAB_PENDING`, awaiting another specimen.

A `POSITIVE` result triggers the full confirmed-rabid cascade, whose secondary effects must all be applied. The case moves from `LAB_PENDING` to `CONFIRMED_RABID`. Any non-terminal PEP recommendation on the case has its `indication` forced to `INITIATE`, and, if it was still `NOT_INDICATED` or `DEFER`, its status is set to `RECOMMENDED`. The surveillance region whose `region_code` equals the case's `region_code` has its `confirmed_positive_count` increased by one, and that region's `alert_status` is then recomputed (Section 3.8). If no region matches the case's `region_code`, the surveillance rollup is a no-op.

A resolved case is closed by an `Epidemiologist` (or `HealthDeptAdmin`): a case whose status is `CONFIRMED_RABID` or `CLEARED` moves to the terminal `CLOSED`, after which no further transitions are permitted; closing a case in any other status is rejected with `ERR_INVALID_STATE`.

### 3.6. Post-Exposure Prophylaxis

The victim's prophylaxis is tracked as a **PEPRecommendation**, owned by the `Epidemiologist` (with `HealthDeptAdmin` able to act throughout). Creating a recommendation for a case requires the `expected_bite_case_version` concurrency guard of Section 2.6; on success any prior recommendation on the case that is still `RECOMMENDED` is moved to `SUPERSEDED`, a new recommendation is created, and the bite case's `version` is incremented by one. A create whose `expected_bite_case_version` no longer matches the case is rejected with `ERR_STALE_CASE_VERSION`, since the case has advanced (for example a lab-positive cascade or an earlier revision) and this writer's view is stale.

At creation the recommendation's `indication` is copied from the parent case's `pep_indication`. A recommendation created for a case whose indication is `NOT_INDICATED` is persisted directly in the terminal status `NOT_INDICATED` with `projected_doses` of zero; otherwise it begins in status `RECOMMENDED`. The provisional dose projection is fixed at creation and assumes the full regimen: `rig_indicated` is true exactly when the `indication` is `INITIATE` and the parent case's `wound_category` is `CATEGORY_III`, meaning rabies immune globulin is indicated. The `projected_doses` is four when the `indication` is `INITIATE` and zero otherwise. The `projected_cost_cents` is the `projected_doses` multiplied by the per-dose cost of 30,000 cents, plus a one-time rabies immune globulin cost of 120,000 cents when `rig_indicated` is true. The standard completed regimen is four doses.

Doses are administered one at a time by an `Epidemiologist`. Administering the first dose is permitted only when the recommendation is `RECOMMENDED` and its `indication` is `INITIATE` or `DEFER`; it moves the recommendation from `RECOMMENDED` to `INITIATED` and sets `doses_administered` to one. Each further dose requires the recommendation to be `INITIATED` with `doses_administered` still below `projected_doses`, and increments `doses_administered` by one, keeping the recommendation `INITIATED`. When the dose being administered is the final one — that is, when `doses_administered` plus one equals `projected_doses` — `doses_administered` is set to `projected_doses` and the recommendation moves from `INITIATED` to the terminal `COMPLETED`. Administering against a recommendation not in an eligible state is rejected with `ERR_INVALID_STATE`.

Each administration recomputes the actual cost. The `final_cost_cents` is the `doses_administered` multiplied by the per-dose cost of 30,000 cents, plus the 120,000-cent immune-globulin cost when `rig_indicated` is true and at least one dose has been administered. Because it counts only actual doses, `final_cost_cents` diverges from `projected_cost_cents` whenever prophylaxis stops early.

An `Epidemiologist` **discontinues** an `INITIATED` recommendation once the animal is proven safe. Discontinuation requires cross-entity clearance — the case's animal must be `RELEASED`, or the case must have a specimen whose `result` is `NEGATIVE` — and this clearance check has precedence over the state check; absent clearance the request is rejected with `ERR_ANIMAL_NOT_CLEARED`, and if the recommendation is not `INITIATED` it is rejected with `ERR_INVALID_STATE`. Discontinuation moves the recommendation to the terminal `DISCONTINUED` and fixes `final_cost_cents` at the actual doses administered. A recommendation's `status` therefore ranges over `NOT_INDICATED`, `RECOMMENDED`, `INITIATED`, `COMPLETED`, `DISCONTINUED`, and `SUPERSEDED`, and its `case_id` ties it to the case whose victim it concerns.

### 3.7. Owner Compliance and Citations

Owner accountability is enforced through **Citations**. An `AnimalControlOfficer` (or `HealthDeptAdmin`) issues a citation manually — for example for `NO_CURRENT_VACCINATION` or `UNLICENSED_ANIMAL` — supplying the `owner_id`, the `case_id`, and a non-empty `violations` array whose entries are each one of `QUARANTINE_BREACH`, `NO_CURRENT_VACCINATION`, `FAILURE_TO_SURRENDER`, or `UNLICENSED_ANIMAL`. The quarantine-breach cascade of Section 3.4 issues a citation by the same rules but with `violations` fixed to `QUARANTINE_BREACH`. A newly issued citation begins in status `ISSUED`, records its `issued_date` as the clock's current value, and computes a `due_date` of the `issued_date` plus thirty days.

The fine is computed at issuance and is immutable thereafter. Each violation contributes a base fine drawn from a fixed schedule: `QUARANTINE_BREACH` is 50,000 cents, `FAILURE_TO_SURRENDER` is 75,000 cents, `NO_CURRENT_VACCINATION` is 25,025 cents, and `UNLICENSED_ANIMAL` is 15,075 cents. The `base_fine_cents` is the plain sum of those base fines across the citation's violations. The `total_fine_cents` — the amount actually owed — applies an 8.5 percent surcharge: for each violation line the base fine is multiplied by 1.085 and that product is rounded to a whole cent with round half up, and only then are the rounded lines summed. Rounding per line before summing is required; summing first and rounding once is incorrect.

Issuing a citation increases the cited owner's `outstanding_fines_cents` and sets the owner's `compliance_status` to `DELINQUENT`. An owner's `outstanding_fines_cents` is the sum of `total_fine_cents` over that owner's citations whose status is `ISSUED`, `CONTESTED`, or `UPHELD`, and it is recomputed on every citation issuance, dismissal, and payment; the owner is `DELINQUENT` when `outstanding_fines_cents` is greater than zero or any owned citation is `ISSUED`, `CONTESTED`, or `UPHELD`, and `COMPLIANT` otherwise.

An `Owner` acts only on their own citations. An owner may **contest** an `ISSUED` citation, optionally supplying a `reason`; this moves the citation to `CONTESTED`, and the citation still counts toward the owner's outstanding fines. A contested citation goes to a hearing resolved by an `Epidemiologist` (deliberately not the issuing officer), who supplies a `resolution`: `UPHELD` moves the citation from `CONTESTED` to `UPHELD` and leaves it owed, while `DISMISSED` moves it from `CONTESTED` to the terminal `DISMISSED` and reduces the owner's `outstanding_fines_cents` by that citation's `total_fine_cents`, recomputing `compliance_status`.

An `Owner` **pays** a citation that is `ISSUED` or `UPHELD` by supplying a `payment_amount_cents`. Three checks apply in order: the citation must be in a payable state (`ISSUED` or `UPHELD`), otherwise `ERR_INVALID_STATE`; the acting owner must own the citation, otherwise `ERR_NOT_CITATION_OWNER`; and the `payment_amount_cents` must exactly equal the citation's `total_fine_cents`, otherwise `ERR_PAYMENT_AMOUNT_MISMATCH`. The same ownership requirement guards contesting: an owner contesting or paying a citation they do not own is rejected with `ERR_NOT_CITATION_OWNER`. A successful payment moves the citation to the terminal `PAID`, decreases the owner's `outstanding_fines_cents`, and recomputes `compliance_status`. A citation's `status` therefore ranges over `ISSUED`, `CONTESTED`, `UPHELD`, `DISMISSED`, and `PAID`.

### 3.8. Surveillance and Wildlife Exposure

Surveillance ties confirmed cases and wildlife sightings to geographic regions. A `HealthDeptAdmin` creates a **SurveillanceRegion** with a `region_code`, which must be unique — a duplicate is rejected with `ERR_DUPLICATE_REGION_CODE` — and an optional `positive_threshold` defaulting to 3. A new region starts with `confirmed_positive_count` and `wildlife_exposure_count` at zero and `alert_status` `NORMAL`.

The region's `confirmed_positive_count` is the number of bite cases sharing its `region_code` that have reached `CONFIRMED_RABID`; it is incremented by the lab-positive cascade of Section 3.5, which selects the region by matching `region_code` against the confirmed case's `region_code`. Each increment recomputes `alert_status`: it is `NORMAL` when `confirmed_positive_count` is zero, `ELEVATED` when the count is greater than zero but less than the region's `positive_threshold`, and `OUTBREAK` when the count is at or above the `positive_threshold` (the threshold comparison is inclusive).

An `IntakeOfficer` or `Epidemiologist` (or `HealthDeptAdmin`) files a **WildlifeExposureReport** under a region, supplying the `region_id`, the wildlife `species` (one of `BAT`, `RACCOON`, `SKUNK`, `FOX`, `COYOTE`, or `OTHER`), the `exposure_datetime`, the `exposure_type` (one of `DIRECT_CONTACT`, `BITE`, or `INDOOR_FOUND_BAT`), and optionally the `disposition` of the wild animal (one of `RELEASED`, `EUTHANIZED`, `ESCAPED`, or `TESTED`, defaulting to `ESCAPED`). Filing a report increases the region's `wildlife_exposure_count` by one. A region's reporting view therefore exposes `confirmed_positive_count`, `wildlife_exposure_count`, and `alert_status` together.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or transition an existing resource, and read operations, return `200 OK`. The logical-clock capability returns `200 OK`. The request body, response body, and side effects of each endpoint are described in the workflow narratives of Section 3; the table below lists only the surface.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/v1/owners` | Register an animal owner | `IntakeOfficer`, `HealthDeptAdmin` |
| GET | `/api/v1/owners/{id}` | Fetch an owner with computed compliance | `IntakeOfficer`, `Epidemiologist`, `Veterinarian`, `AnimalControlOfficer`, `HealthDeptAdmin` |
| POST | `/api/v1/animals` | Record or identify an animal | `IntakeOfficer`, `AnimalControlOfficer`, `HealthDeptAdmin` |
| GET | `/api/v1/animals/{id}` | Fetch an animal | `IntakeOfficer`, `Epidemiologist`, `Veterinarian`, `AnimalControlOfficer`, `HealthDeptAdmin` |
| GET | `/api/v1/animals` | List animals; filter by owner or status | `IntakeOfficer`, `Epidemiologist`, `Veterinarian`, `AnimalControlOfficer`, `HealthDeptAdmin` |
| POST | `/api/v1/animals/{id}/capture` | Record capture of an at-large animal | `AnimalControlOfficer`, `HealthDeptAdmin` |
| POST | `/api/v1/animals/{id}/disposition` | Record disposition or mark at-large | `AnimalControlOfficer`, `Veterinarian`, `HealthDeptAdmin` |
| POST | `/api/v1/bite-cases` | Intake a bite report; compute risk and PEP indication | `IntakeOfficer`, `HealthDeptAdmin` |
| GET | `/api/v1/bite-cases/{id}` | Fetch a bite case (includes version) | `IntakeOfficer`, `Epidemiologist`, `Veterinarian`, `AnimalControlOfficer`, `HealthDeptAdmin` |
| GET | `/api/v1/bite-cases` | List bite cases; filter by animal, status, or region | `IntakeOfficer`, `Epidemiologist`, `Veterinarian`, `AnimalControlOfficer`, `HealthDeptAdmin` |
| POST | `/api/v1/bite-cases/{id}/close` | Close a resolved case | `Epidemiologist`, `HealthDeptAdmin` |
| POST | `/api/v1/quarantine-facilities` | Create a confinement facility | `HealthDeptAdmin` |
| GET | `/api/v1/quarantine-facilities/{id}` | Fetch a facility with occupancy | `Veterinarian`, `AnimalControlOfficer`, `HealthDeptAdmin` |
| POST | `/api/v1/bite-cases/{id}/quarantine-orders` | Issue a 10-day confinement order (OCC on case) | `Veterinarian`, `AnimalControlOfficer`, `HealthDeptAdmin` |
| GET | `/api/v1/quarantine-orders/{id}` | Fetch a quarantine order | `Veterinarian`, `AnimalControlOfficer`, `Epidemiologist`, `HealthDeptAdmin` |
| GET | `/api/v1/quarantine-orders` | List quarantine orders; filter by case, animal, facility, or status | `Veterinarian`, `AnimalControlOfficer`, `Epidemiologist`, `HealthDeptAdmin` |
| POST | `/api/v1/quarantine-orders/{id}/complete` | Complete quarantine and release healthy animal | `Veterinarian`, `HealthDeptAdmin` |
| POST | `/api/v1/quarantine-orders/{id}/breach` | Record a confinement breach | `AnimalControlOfficer`, `HealthDeptAdmin` |
| POST | `/api/v1/quarantine-orders/{id}/convert-to-specimen` | Convert quarantine to specimen submission | `Veterinarian`, `HealthDeptAdmin` |
| POST | `/api/v1/bite-cases/{id}/specimens` | Submit a brain specimen | `Veterinarian`, `HealthDeptAdmin` |
| GET | `/api/v1/specimens/{id}` | Fetch a specimen | `Veterinarian`, `Epidemiologist`, `HealthDeptAdmin` |
| GET | `/api/v1/specimens` | List specimens; filter by case or animal | `Veterinarian`, `Epidemiologist`, `HealthDeptAdmin` |
| POST | `/api/v1/specimens/{id}/report-result` | Report a lab result | `Veterinarian`, `HealthDeptAdmin` |
| POST | `/api/v1/bite-cases/{id}/pep-recommendations` | Create or supersede a PEP recommendation (OCC on case) | `Epidemiologist`, `HealthDeptAdmin` |
| GET | `/api/v1/bite-cases/{id}/pep-recommendations` | List PEP recommendations for a case | `Epidemiologist`, `Veterinarian`, `HealthDeptAdmin` |
| POST | `/api/v1/pep-recommendations/{id}/administer-dose` | Record one administered dose | `Epidemiologist`, `HealthDeptAdmin` |
| POST | `/api/v1/pep-recommendations/{id}/discontinue` | Discontinue prophylaxis once cleared | `Epidemiologist`, `HealthDeptAdmin` |
| POST | `/api/v1/citations` | Issue a citation | `AnimalControlOfficer`, `HealthDeptAdmin` |
| GET | `/api/v1/citations/{id}` | Fetch a citation (own citations for owners) | `Owner`, `AnimalControlOfficer`, `Epidemiologist`, `HealthDeptAdmin` |
| GET | `/api/v1/citations` | List citations; filter by owner, case, or status | `Owner`, `AnimalControlOfficer`, `Epidemiologist`, `HealthDeptAdmin` |
| POST | `/api/v1/citations/{id}/contest` | Owner contests a citation | `Owner`, `HealthDeptAdmin` |
| POST | `/api/v1/citations/{id}/resolve` | Resolve a contested citation | `Epidemiologist`, `HealthDeptAdmin` |
| POST | `/api/v1/citations/{id}/pay` | Owner pays a citation | `Owner`, `HealthDeptAdmin` |
| POST | `/api/v1/surveillance-regions` | Create a surveillance region | `HealthDeptAdmin` |
| GET | `/api/v1/surveillance-regions/{id}` | Fetch a region with counts and alert status | `IntakeOfficer`, `Epidemiologist`, `Veterinarian`, `AnimalControlOfficer`, `HealthDeptAdmin` |
| POST | `/api/v1/surveillance-regions/{id}/wildlife-exposure-reports` | File a wildlife-exposure report | `IntakeOfficer`, `Epidemiologist`, `HealthDeptAdmin` |
| GET | `/api/v1/surveillance-regions/{id}/wildlife-exposure-reports` | List wildlife reports for a region | `IntakeOfficer`, `Epidemiologist`, `Veterinarian`, `AnimalControlOfficer`, `HealthDeptAdmin` |
| POST | `/api/v1/_clock/set_current_utc` | Advance the logical clock (test-driving) | `HealthDeptAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_OWNER_NOT_FOUND` | 404 |
| `ERR_ANIMAL_NOT_FOUND` | 404 |
| `ERR_CASE_NOT_FOUND` | 404 |
| `ERR_FACILITY_NOT_FOUND` | 404 |
| `ERR_QUARANTINE_ORDER_NOT_FOUND` | 404 |
| `ERR_SPECIMEN_NOT_FOUND` | 404 |
| `ERR_PEP_NOT_FOUND` | 404 |
| `ERR_CITATION_NOT_FOUND` | 404 |
| `ERR_REGION_NOT_FOUND` | 404 |
| `ERR_DUPLICATE_REGION_CODE` | 409 |
| `ERR_FACILITY_REQUIRED` | 422 |
| `ERR_STALE_CASE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ANIMAL_SYMPTOMATIC` | 409 |
| `ERR_ANIMAL_NOT_DECEASED` | 409 |
| `ERR_ANIMAL_NOT_CLEARED` | 409 |
| `ERR_QUARANTINE_NOT_ELAPSED` | 409 |
| `ERR_ANIMAL_QUARANTINE_OVERLAP` | 409 |
| `ERR_FACILITY_AT_CAPACITY` | 409 |
| `ERR_NOT_CITATION_OWNER` | 403 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 |
