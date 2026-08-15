# Crop Hail & Livestock Mortality Insurance API — Product Requirements Document

## 1. Introduction

Private crop-hail and livestock mortality insurance occupies the gap that federal multi-peril crop insurance leaves open: a grower may carry a federal policy for catastrophic coverage and still want private hail protection on a specific county's acreage, or mortality coverage on a herd of cattle, a string of horses, or a flock of poultry. The carrier operating these lines lives and dies by disciplined data collection — acres and head counts reported against firm deadlines, rates maintained per county and crop or per species and value band, losses inspected in the field, and indemnities computed through an auditable waterfall of reductions. This document specifies the API through which such a carrier runs its book of business, from grower registration and rate-table publication through policy binding, acreage and head reporting, claims adjustment, loss determination, payment, and renewal.

The system is built around a carrier-scoped resource tree mounted under `/carriers`. Every carrier operates on its own logical clock so that deadline, window, and delinquency behavior stays deterministic; all time-driven state changes — policy activation and expiration, billing delinquency, claim auto-closure, federal policy expiration — are evaluated against that clock rather than wall-clock time. Two product lines share one policy skeleton: crop-hail policies insure declared acreage at a fixed per-acre exposure, while livestock mortality policies insure a declared head count at a declared value per animal. Claims follow a strict segregation-of-duties model in which the field adjuster who inspects a loss can never be the approver who decides it, and a small set of optimistic-concurrency guards protects the policy aggregate against writers working from stale reads.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once the identity headers are accepted, the caller's role must appear in the target endpoint's authorized role list; otherwise the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes five roles, spelled exactly as follows: `PlatformAdmin`, `Underwriter`, `Policyholder`, `Adjuster`, and `ClaimsApprover`.

When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the platform administrator creates carriers and reads everything beneath them. When `X-User-Role` is `Underwriter`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; underwriters run the carrier's back office — grower and adjuster registration, rate tables, federal policy registration, policy creation, binding and cancellation, coverage units, dual-coverage linking, renewals, debarment, and the test-driving clock. When `X-User-Role` is `ClaimsApprover`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, but the server records it as `reviewer_id` on each loss determination for the segregation-of-duties audit trail; claims approvers assign adjusters, issue determinations, and issue, clear, or void indemnity payments.

Two roles are entity-backed. When `X-User-Role` is `Policyholder`, `X-User-ID` is the `id` of the acting Grower. Policyholders submit acreage and head reports, file first notice of loss, submit veterinary documentation, withdraw claims, and pay premiums. When `X-User-Role` is `Adjuster`, `X-User-ID` is the `id` of the acting Adjuster. Adjusters submit field inspections and forward inspected claims for review — they can never decide a loss. Beyond endpoint role membership, the server enforces caller identity only where a workflow states so explicitly — the assigned-adjuster checks of §3.7; it applies no ownership scoping, so a Policyholder may act on any grower's resources and reads are never restricted by ownership.

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

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

Several list endpoints additionally accept optional filters: `status` on growers, rate tables, federal crop policies, and coverage units; `rating_kind` on rate tables; `grower_id` on policies and federal crop policies; `lifecycle_state` and `billing_state` on policies; and `claim_state` on claims.

### 2.4. Common Resource Properties

Every resource in the system — carriers, growers, adjusters, rate tables, federal crop policies, policies, coverage units, acreage and head reports, claims, field inspections, veterinary reports, loss determinations, indemnity payments, dual coverage links, renewals, and premium payments — carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments with every modification to the resource, including modifications caused by cascaded side effects from operations on related resources.

Updates to derived fields — a policy's billing posture, a claim's documentation posture, a recomputed premium reserve — count as mutations: they refresh `updated_at` and increment `version`. The policy record additionally carries a `version_note` annotation documenting that its `version` is the optimistic-concurrency target and that it advances on every mutation, including cascaded side effects: a posted premium payment, a claim approval, or a renewal decision all increment the policy's version even when the client's request named a different resource.

### 2.5. The Carrier Logical Clock and Time-Driven State Progression

Each carrier runs on its own logical clock, exposed as `current_utc` on the carrier record. The clock starts at `2026-08-01T00:00:00Z` when the carrier is created and advances only when an `Underwriter` invokes the carrier's clock-setting capability with a `to_iso8601` timestamp; it never moves on its own. Any valid ISO 8601 timestamp is accepted — the server enforces no monotonicity, so the clock may be set backward — and setting the clock refreshes the carrier's own `updated_at` and `version`. Every deadline, window, and delinquency rule in this document is evaluated against `current_utc`, and every system timestamp described in §3 — report submissions, first notice of loss, inspections, decisions, payments — is stamped from it.

Advancing the clock is not a passive read: it triggers every automatic transition whose condition has come due. A `BOUND` policy activates when the clock reaches its `effective_date`, provided its billing state is one of `BILLED`, `PARTIALLY_PAID`, or `PAID_IN_FULL`; an `ACTIVE` policy expires when the clock reaches its `expiration_date`; a policy whose premium remains underpaid thirty days after binding falls delinquent; a claim still in `REPORTED` thirty days after its loss closes as `CLOSED_UNTIMELY`; and a federal crop policy expires when the clock reaches its own expiration date. Each such automatic transition is a mutation that refreshes `updated_at` and increments `version` on the affected resource.

### 2.6. Nested Resource Retrieval and Path Validation

URLs in this API chain identifiers from the carrier downward — `carrierId` first, then perhaps `growerId`, `adjusterId`, `rateTableId`, or `fciId` for the carrier-level registries, or `policyId`, then `unitId`, then `claimId`, and finally `paymentId` for the policy tree. The server validates these identifiers in a strict left-to-right order: the first identifier in the path that does not correspond to an existing resource produces a `404 Not Found` rejection with `ERR_NOT_FOUND`, and no further validation is attempted. A request addressed to a coverage unit under a policy that does not exist therefore fails on `policyId` before `unitId` is ever examined, and a request under a carrier that does not exist fails on `carrierId` before anything else. Resource identifiers carried in the request body — a grower's `grower_id` on federal-policy or policy creation, a `prior_policy_id`, a claim's `coverage_unit_id`, an assignment's `adjuster_id`, a link's `federal_crop_policy_id` — are likewise resolved to existing resources of the same carrier (and, where the path implies a parent, beneath that parent), after payload-shape validation and before the workflow's state and business checks; a miss produces the same `ERR_NOT_FOUND` (HTTP 404).

### 2.7. Money, Precision, and Rounding

All monetary values in the system are integer cents; no fractional cents are stored or returned. Rates are likewise integer expressions: `rate_per_100_cents_of_liability` states how many premium cents are owed per 100 cents of liability, so a value of 350 corresponds to $3.50 per $100 of liability. Crop-hail exposure is built from a fixed per-acre constant of $400.00 — that is, 40,000 cents of liability per declared acre.

Rounding discipline is pinned per calculation and restated where each calculation appears in §3, under three standing rules. Per-unit premiums are rounded half up to whole cents before any aggregation takes place. The provisional indemnity computed at field-inspection time applies no intermediate truncation and is rounded half up only at its final step. The final-indemnity waterfall at loss determination truncates each intermediate step to whole cents before the next step runs, then rounds half up at its final step. Percentages — surcharge tiers, coverage reductions, late-notice penalties, the dual-coverage offset — are whole-number percents, and day counts are whole days, with any partial day of lateness rounded up to the next whole day.

### 2.8. Optimistic Concurrency Control on Policy Writes

Two write operations in this API participate in optimistic concurrency control, and both guard the policy aggregate. No other endpoint accepts a version field.

Creating a renewal requires the request to carry `expected_prior_policy_version`, holding the `version` of the policy being renewed as the client last observed it. If the prior policy's current `version` has advanced since that read — because a premium payment posted, a claim was filed, or any other mutation landed in between — the renewal is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from renewing a policy whose current state it has not observed.

Issuing a loss determination requires the request to carry `expected_policy_version`, holding the `version` of the claim's parent policy as the approver last observed it. If the policy's `version` has advanced since that read — for example because a premium payment, a cancellation, or a renewal cascaded a version bump between the approver's read and the determination write — the determination is rejected with `ERR_STALE_VERSION` (HTTP 412).

On both operations the version check runs before any business validation, so a stale write surfaces as `ERR_STALE_VERSION` rather than being masked by a later rule. Both fields are non-optional on their respective requests.

### 2.9. Validation Pipeline and Evaluation Order

Every request passes through a fixed validation pipeline. First, the presence and shape of the identity headers are checked (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, role authorization is enforced (`ERR_INSUFFICIENT_PERMISSIONS`). Third, path identifiers are resolved left to right (`ERR_NOT_FOUND`). Fourth, on the two concurrency-guarded writes, the expected-version check runs (`ERR_STALE_VERSION`) — ahead of any business rule. Fifth, the target resource must be in a state that permits the requested transition (`ERR_INVALID_STATE`, HTTP 409, or the more specific state-guard error the workflow declares). Only then do business validations run, in the priority order stated alongside each workflow in §3: business-safety checks (segregation of duties, the necropsy requirement, livestock documentation completeness) come before business-temporal checks (the coverage window, late notice of loss, report-before-coverage), which precede referential and constraint checks (adjuster territory and capacity, rate-table overlap, rate availability at bind, renewal eligibility, dual-coverage matching), with the fiscal guards (premium overpayment, the indemnity reserve cap) evaluated last.

Independently of this pipeline, malformed payloads — a missing required field, a field outside the endpoint's declared set, a value of the wrong type, or an enum value outside the declared set — are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Carrier Onboarding, the Grower Registry, and the Adjuster Roster

A `PlatformAdmin` brings a carrier onto the platform by supplying its `carrier_code` — unique across all carriers, with a duplicate rejected with `ERR_INVALID_REQUEST` (HTTP 400) — its `legal_name`, and its `reinsurance_treaty_attachment_cents`, the aggregate indemnity level above which the carrier's reinsurance treaty attaches. The carrier's logical clock starts at creation. Every record stored beneath the carrier — growers, adjusters, rate rows, federal crop policies, and the policies themselves — carries a `carrier_id` reference back to its owning carrier.

An `Underwriter` registers each insured grower with a `full_name`, the `tax_id_last4` (the last four digits of the grower's SSN or EIN), a contact `email`, and the grower's primary `county_code` (a five-character FIPS code) and two-letter `state_code`. A newly registered grower's `status` begins `ACTIVE` and its `prior_claims_count` begins at zero; the count tracks the grower's claims in `APPROVED` or `PAID` status across all of that grower's policies and drives the high-risk surcharge described in §3.4. The `continuous_coverage_since` field stays null until the grower's first renewal, when it is set from the start of the earliest un-broken coverage period. Growers who fall behind on premium are suspended automatically (§3.6); proven fraud leads an underwriter to debar the grower (§3.9), moving the grower to the terminal `DEBARRED` status.

The adjuster roster is likewise underwriter-maintained. Each adjuster is registered with a `full_name`, a `license_number` unique within the carrier — a duplicate is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — the `county_codes` the adjuster is licensed to inspect in, the `species_qualified` the adjuster may appraise (drawn from `CATTLE`, `SWINE`, `POULTRY`, `EQUINE`, and `SHEEP`), and a `capacity_max_open_claims` ceiling on concurrently open assignments. Adjusters begin with `status` `ACTIVE`; an adjuster set `INACTIVE` is ineligible for new assignments. An adjuster's open load counts the claims assigned to them that sit in `REPORTED`, `INSPECTION_SCHEDULED`, `INSPECTED`, or `UNDER_REVIEW`.

### 3.2. Rating Infrastructure: Rate Tables and Their Publication

Premium rating is data-driven, through rate-table rows that underwriters maintain per carrier. Each row declares a `rating_kind` — `CROP_HAIL` or `LIVESTOCK_MORTALITY` — and the axis along which it rates. A crop-hail row keys on `county_code` and `crop_code`, and its `species`, `value_band_floor_cents`, and `value_band_ceiling_cents` are absent. A livestock row keys on `species` and an animal-value band whose `value_band_floor_cents` is inclusive and whose `value_band_ceiling_cents` is exclusive and must exceed the floor (a band whose ceiling does not exceed its floor is rejected with `ERR_INVALID_REQUEST`); its `county_code` and `crop_code` are absent. Every row carries `rate_per_100_cents_of_liability` and an effectiveness window: `effective_from` is inclusive, `effective_to` is exclusive, and a null `effective_to` leaves the row open-ended. Creating a row whose `effective_to` does not fall after its `effective_from` is rejected with `ERR_INVALID_DATE_RANGE` (HTTP 422); the same guard applies to the date pairs on policy applications and federal crop policies.

New rows are `DRAFT` and inert. Publishing a row moves it to `PUBLISHED`, but only when no other `PUBLISHED` row exists with the same `rating_kind` and the same county-and-crop pair (crop-hail) — or the same `rating_kind`, species, and an overlapping value band (livestock) — whose effectiveness window overlaps the candidate's window; an overlap is rejected with `ERR_RATE_TABLE_OVERLAP` (HTTP 409). A published row may later be retired by superseding it, moving it from `PUBLISHED` to the terminal `SUPERSEDED` status. Publishing a row that is not `DRAFT`, or superseding a row that is not `PUBLISHED`, is rejected with `ERR_INVALID_STATE`.

Only `PUBLISHED` rows participate in rating; `DRAFT` and `SUPERSEDED` rows are invisible to premium calculation. When more than one published row matches a coverage unit — possible only while effectiveness windows overlap across successive publications — the row with the latest `effective_from` wins, and any remaining tie is broken by the earliest `created_at`.

### 3.3. Federal Crop Policies and Dual-Coverage Linking

Many growers carry federal multi-peril coverage alongside the carrier's private crop-hail policy, and the interaction between the two is priced into claim settlement. An underwriter registers a grower's federal policy by providing the `grower_id`, the FCIC-issued `fci_policy_number`, the federal `coverage_level_pct` (between 0.50 and 0.85 inclusive), the `crop_code` and `county_code` where the federal coverage attaches, the `effective_date` and `expiration_date`, and the federal `liability_cents`. Registration makes the federal policy `ACTIVE`; it expires automatically, moving to `EXPIRED`, when the carrier's clock reaches its `expiration_date`, and an underwriter may cancel an active federal policy, moving it to `CANCELLED`.

With both policies on file, an underwriter may link a private crop-hail policy to a federal crop policy by submitting the `federal_crop_policy_id`. The link is refused with `ERR_DUAL_COVERAGE_MISMATCH` (HTTP 422) unless the federal policy is `ACTIVE` and its crop and county match the private policy's coverage units. A successful link is stamped with `established_at` from the logical clock, fixes `offset_pct_of_federal_liability` at 20, and is recorded on the private policy as its `dual_coverage_link_id` — linking a policy that already carries a link replaces that pointer with the newest link; the link record also carries the private policy's `policy_id`. The 20% figure is the dual-coverage offset applied at loss determination (§3.8): when a linked claim settles and the federal policy was `ACTIVE` on the loss date with overlapping crop and county, twenty percent of the federal `liability_cents` is offset against the indemnity — never more than the indemnity remaining at that step — and the offset applied is recorded as `applied_dual_coverage_offset_cents`.

### 3.4. From Application to Bound Policy: Coverage Units, Deadlines, and Premium

An underwriter opens a policy application by naming the insured grower (`grower_id`), the `policy_kind` (`CROP_HAIL` or `LIVESTOCK_MORTALITY`), and the coverage period: `effective_date` is inclusive, `expiration_date` is exclusive, and a pair whose expiration does not fall after its effective date is rejected with `ERR_INVALID_DATE_RANGE`. An application may also name a `prior_policy_id` when it continues an earlier policy; a `prior_policy_id` that does not resolve to an existing policy is rejected with `ERR_NOT_FOUND` (HTTP 404), and one naming a policy of a different grower is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — both already at application creation. The server mints a unique `policy_number` of the form `POL-<carrier_code>-<seq>`, where `<seq>` is a per-carrier sequential counter starting at 1, stamps the new policy into `APPLICATION` lifecycle with billing `UNBILLED` and `claims_posture` `OPEN`, and computes three reporting deadlines: for crop-hail policies the `acreage_report_deadline` falls twenty-one days after the effective date and the `harvest_report_deadline` fourteen days before expiration; for livestock policies the `head_report_deadline` falls ten days after the effective date.

Two pricing annotations are computed at application time. The `high_risk_surcharge_pct` reads the grower's `prior_claims_count`: zero surcharge when the grower has at most one approved-or-paid claim, ten percent when the count is two or three, and twenty-five percent when it is four or more — the tier boundaries are inclusive. When `prior_policy_id` is present, the `continuous_coverage_carryover_credit_cents` is five percent of the prior policy's `premium_cents`, rounded half up to whole cents, granted only when the prior policy expired — was not cancelled — no more than seven days before the new policy's effective date; in every other case the credit is zero.

Coverage units give the application substance, and underwriters add them while the policy is still an application — adding a unit to a policy in any other lifecycle state is rejected with `ERR_INVALID_STATE` (HTTP 409). A crop-hail unit declares `county_code`, `crop_code`, and whole-acre `declared_acres` between 1 and 100000; a livestock unit declares its `species`, a `declared_head_count` between 1 and 100000, and the `per_head_value_cents` at which each animal is insured (a positive integer). The unit's `unit_kind` mirrors the policy's kind, and each unit records its parent `policy_id`. Liability is computed immediately: a crop-hail unit's `liability_cents` is its declared acres multiplied by the 40,000-cent per-acre exposure constant, while a livestock unit's `liability_cents` is its head count multiplied by the per-head value. Each unit's `premium_cents` is then its liability multiplied by the matching published row's `rate_per_100_cents_of_liability` and divided by 10,000, rounded half up to whole cents — a crop-hail unit matches a row on county and crop, while a livestock unit matches when its species equals the row's and its per-head value falls at or above the band floor and strictly below the band ceiling. This per-unit figure uses the rate in effect at the current clock when the unit is created — zero when no published row matches at that moment — and it is recomputed against the binding clock time and frozen at bind. Every unit begins life `PENDING_REPORT`.

Binding is the underwriter's commitment point, and its checks run in a fixed order. The policy must still be in `APPLICATION` (`ERR_POLICY_NOT_IN_APPLICATION`, HTTP 409); at least one coverage unit must exist (`ERR_NO_COVERAGE_UNITS`, HTTP 422); every unit must match a `PUBLISHED` rate row whose effectiveness window contains the binding clock time (`ERR_NO_ACTIVE_RATE_TABLE`, HTTP 422); the grower must be `ACTIVE` (`ERR_GROWER_NOT_ACTIVE`, HTTP 409); and when the application names a `prior_policy_id`, that policy must exist and belong to the same grower (`ERR_INVALID_REQUEST`, HTTP 400). Binding then re-reads the surcharge tier from the grower's current `prior_claims_count` and aggregates the premium in pinned order — each unit's premium is rounded half up to whole cents first, then the units are summed; the high-risk surcharge is applied to that sum as a multiplier of one plus the surcharge percent, again rounded half up; and the carryover credit is subtracted last, with the result floored at zero — and freezes it as the policy's `premium_cents`. The policy moves from `APPLICATION` to `BOUND`, its billing becomes `BILLED`, its `premium_reserve_cents` is established at sixty percent of the frozen premium rounded down to a whole cent, and the policy's `version` increments. Thereafter the policy activates automatically, moving from `BOUND` to `ACTIVE`, when the clock reaches the effective date — so long as billing has not gone delinquent.

The policy's `claims_posture` is derived, never set directly: it reads `OPEN` unless billing has gone `DELINQUENT` or the lifecycle has reached `EXPIRED`, `CANCELLED`, or `NON_RENEWED`, in which case it reads `RESTRICTED`. A restricted policy refuses new claim-driven adjuster assignments with `ERR_POLICY_RESTRICTED` (HTTP 409), as §3.7 describes.

### 3.5. Acreage and Head Reporting: Deadlines, Lateness, and Coverage Reduction

Once a policy is bound or active, the policyholder owes reports against the deadlines computed at application time; a report submitted while the policy is in any other lifecycle state is rejected with `ERR_INVALID_STATE` (HTTP 409), and a report of the wrong family for the unit's kind — an acreage report on a livestock unit or a head report on a crop-hail unit — is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A crop-hail unit receives acreage reports — the planting report and the harvest report — submitted with a `report_kind` of `PLANTING` or `HARVEST` and the `reported_acres` actually planted or harvested. A livestock unit receives head reports with a `report_kind` of `INITIAL`, `INTERIM`, or `FINAL` and the `reported_head_count` on hand. Each report is stamped with `submitted_at` from the logical clock and records its `coverage_unit_id`; a report submitted before the policy's `effective_date` is rejected with `ERR_REPORT_BEFORE_COVERAGE` (HTTP 422), a guard that applies to both report families.

Timeliness is computed per report. A planting report is timely when submitted on or before the `acreage_report_deadline`; a harvest report when submitted on or before the `harvest_report_deadline`; an initial head report when submitted on or before the `head_report_deadline`. Interim and final head reports are always timely while the policy is `ACTIVE`. A timely report sets `is_timely` true, leaves `lateness_days` and `coverage_reduction_pct` at zero, and — when the unit is still waiting on its first report — moves it from `PENDING_REPORT` to `REPORTED`. A late planting, harvest, or initial head report instead counts `lateness_days` as the whole days past the deadline, with any partial day rounded up to the next whole day, and sets `coverage_reduction_pct` to five percent per late day, capped at one hundred percent; a unit whose first report arrives late falls from `PENDING_REPORT` to `LAPSED_REPORT`, as it also does when the deadline passes with no report at all, or when the policy expires while the unit is still `PENDING_REPORT`. Only a unit still `PENDING_REPORT` transitions on a report: a unit that has already fallen to `LAPSED_REPORT` remains `LAPSED_REPORT` even when a report later arrives.

The reduction recorded on the latest late report follows the unit into claim settlement, where it scales the indemnity down (§3.7, §3.8); interim and final head reports never reduce coverage. Note the interplay with claim intake: because a claim can only be opened against a unit currently in `REPORTED`, a unit that has fallen to `LAPSED_REPORT` no longer accepts claims, while a unit that reported on time and later filed a late second report keeps its `REPORTED` standing but carries the late report's reduction into any settlement.

### 3.6. Premium Billing, Payments, and Delinquency

Binding bills the policy. From then on the policyholder posts premium payments with an `amount_cents` that must be greater than zero; each payment is stamped with `posted_at` from the logical clock and records its parent `policy_id`. Payments are accepted only while the policy's lifecycle is `BOUND` or `ACTIVE` — attempts against a policy in any other lifecycle state are rejected with `ERR_POLICY_NOT_BILLABLE` (HTTP 409) — and a payment that exceeds the outstanding balance, meaning the policy's `premium_cents` less the `premium_paid_cents` already collected, is rejected with `ERR_OVERPAYMENT` (HTTP 422).

Each accepted payment adds its amount to `premium_paid_cents` and moves the billing axis. A payment that falls short of the outstanding balance moves billing from `BILLED` to `PARTIALLY_PAID`; one that brings cumulative payments up to the full premium moves billing from `BILLED` to `PAID_IN_FULL`, or from `PARTIALLY_PAID` to `PAID_IN_FULL`. Delinquency is the clock's doing: when `current_utc` passes thirty days after the binding moment with the premium still underpaid, a policy in `BILLED` or `PARTIALLY_PAID` falls to `DELINQUENT`, its `claims_posture` flips to `RESTRICTED`, its grower's `status` flips to `SUSPENDED`, and the policy's `version` increments. A delinquent policy that later receives enough in payments to reach its full premium returns to `PAID_IN_FULL`; its posture reopens to `OPEN`, and the grower returns to `ACTIVE` provided no other policy of that grower remains delinquent. Every payment-driven transition also refreshes the policy's `updated_at` and increments its `version`.

### 3.7. Claims Intake, Field Inspection, and Veterinary Documentation

A policyholder's first notice of loss opens a claim by naming the `coverage_unit_id` that sustained the loss and the `loss_date`, plus the line-specific particulars: a hail claim carries the grower's initial `percent_damage_estimate_pct` between 1 and 100, while a livestock claim carries the grower's claimed `appraisal_value_cents` and a `deceased_head_count` between one and the unit's `declared_head_count`. The unit must currently be `REPORTED` — filing against a unit in any other status is rejected with `ERR_INVALID_STATE` — and filing moves the unit from `REPORTED` to `UNDER_CLAIM`. The claim's `claim_kind` mirrors the policy's kind (`HAIL_DAMAGE` on crop-hail policies, `LIVESTOCK_MORTALITY` on livestock policies), the claim is anchored to its parent policy via `policy_id`, its `reported_at` is stamped from the logical clock, and it opens in `REPORTED` state with `doc_posture` `DOCS_PENDING` and `adjuster_id` still null.

Two intake checks run in a fixed order. First, the loss must fall inside the coverage period — on or after the policy's `effective_date` and before its `expiration_date` — or the filing is rejected with `ERR_LOSS_DATE_OUT_OF_COVERAGE` (HTTP 422). Second, notice given more than thirty days after the loss is non-payable by rule and is refused at intake with `ERR_LATE_NOTICE_OVER_30D` (HTTP 422); the coverage-window check runs first, so an out-of-coverage loss surfaces as `ERR_LOSS_DATE_OUT_OF_COVERAGE` rather than being masked by the late-notice rule. Notice latency is priced even when the claim is accepted: a hail claim reported within seventy-two hours of the loss, or a livestock claim reported within twenty-four hours, sets `reported_within_window` true and carries no penalty; notice past the window but within seven days of the loss draws a ten-percent `late_notification_penalty_pct`; notice past seven days but within thirty days draws twenty-five percent. The boundaries are inclusive — a report exactly seventy-two or twenty-four hours after the loss is within the window, and one exactly seven days past draws the ten-percent tier.

Assignment of a field adjuster is the claims approver's first act, performed with a payload naming the `adjuster_id`, and its checks also run in a fixed order. The claim must be in `REPORTED` (`ERR_CLAIM_NOT_IN_REPORTED`, HTTP 409). The adjuster must be `ACTIVE` (`ERR_ADJUSTER_NOT_ACTIVE`, HTTP 409). Territorial and qualification fit come next: for hail claims the unit's `county_code` must appear in the adjuster's `county_codes` (`ERR_ADJUSTER_COUNTY_MISMATCH`, HTTP 422), and for livestock claims the unit's `species` must appear in the adjuster's `species_qualified` (`ERR_ADJUSTER_SPECIES_MISMATCH`, HTTP 422). Capacity follows: the adjuster's current open-claim load must be below `capacity_max_open_claims` (`ERR_ADJUSTER_CAPACITY_FULL`, HTTP 409). Finally the policy's `claims_posture` must be `OPEN` (`ERR_POLICY_RESTRICTED`, HTTP 409). A successful assignment records the `adjuster_id` on the claim and moves it from `REPORTED` to `INSPECTION_SCHEDULED`.

The assigned adjuster — and only that adjuster — then submits the field inspection. The payload repeats the `adjuster_id`, which must match the one recorded on the claim, and carries the planned `scheduled_for` time, a required free-form `notes` string, and the observations: `observed_percent_damage_pct` between 0 and 100 for hail, or `observed_appraisal_cents` and `observed_deceased_count` for livestock. The claim must be `INSPECTION_SCHEDULED` (`ERR_CLAIM_NOT_IN_INSPECTION_SCHEDULED`, HTTP 409), and a mismatch between the claim's `adjuster_id` and either the caller's `X-User-ID` or the payload's `adjuster_id` is rejected with `ERR_NOT_ASSIGNED_ADJUSTER` (HTTP 403). One safety gate guards livestock inspections: when the grower's claimed appraisal exceeds $5,000 — 500,000 cents — at least one veterinary report with `necropsy_performed` true must already exist on the claim, or the inspection submission is rejected with `ERR_NECROPSY_REQUIRED` (HTTP 422). A successful submission stamps `inspected_at` from the logical clock, records `within_inspection_window` — true when the inspection occurred within seven days of the claim's `reported_at` — computes the provisional indemnity, writes it to both the inspection's and the claim's `provisional_indemnity_cents`, and moves the claim from `INSPECTION_SCHEDULED` to `INSPECTED`. The inspection record carries its `claim_id` back to the parent claim.

The provisional indemnity is computed differently per line of business. For hail, the unit's `liability_cents` is first scaled down by the `coverage_reduction_pct` of the latest late acreage report — no scaling applies when all acreage reports were timely — and the result is multiplied by the adjuster's `observed_percent_damage_pct` and divided by one hundred. For livestock, the appraisal basis is the lesser of the adjuster's `observed_appraisal_cents` and the grower's claimed `appraisal_value_cents`; that basis is then capped at the `value_band_ceiling_cents` of the rate row matched to the unit (the row frozen at bind) multiplied by the adjuster's `observed_deceased_count` — no band cap applies when the unit matched no rate row — and the capped figure is scaled down by the latest late head report's `coverage_reduction_pct`. In both branches the result is finally scaled down by the claim's `late_notification_penalty_pct`, and the outcome is rounded half up to whole cents at this final step only, with no intermediate truncation.

From `INSPECTED`, the same assigned adjuster forwards the claim for review — the state guard is `ERR_CLAIM_NOT_IN_INSPECTED` (HTTP 409), and the caller must again be the claim's assigned adjuster — moving it from `INSPECTED` to `UNDER_REVIEW`. A policyholder may instead withdraw a claim while it is in `REPORTED` or `INSPECTION_SCHEDULED`; withdrawal from any other state is rejected with `ERR_CLAIM_NOT_WITHDRAWABLE` (HTTP 409). Withdrawal moves the claim to `WITHDRAWN` and releases the unit back to `REPORTED` so it can host a future claim. Claims that sit unworked die of their own accord: when the clock passes thirty days after the `loss_date` with the claim still in `REPORTED`, the claim closes automatically as `CLOSED_UNTIMELY` and the unit likewise returns to `REPORTED`.

Veterinary documentation accrues on livestock claims through policyholder submissions carrying the `veterinarian_license`, a `report_kind` of `VETERINARY_CERTIFICATE`, `NECROPSY_REPORT`, or `THIRD_PARTY_AFFIDAVIT`, the `cause_of_death` — which must be non-empty for veterinary certificates and necropsy reports — whether a necropsy was performed via `necropsy_performed`, and the vet-attested `death_date`, which must fall within two days of the claim's `loss_date` in either direction. Submissions attach to livestock claims only — one addressed to a hail claim is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — and are accepted regardless of the claim's state. Each report is stamped with `submitted_at` and carries its `claim_id`. Every submission recomputes the claim's `doc_posture`: it reads `DOCS_COMPLETE` when a veterinary certificate is on file and — for claims whose appraised value exceeds $5,000 — a necropsy report with `necropsy_performed` true is also on file, and it otherwise remains `DOCS_PENDING`. The `doc_posture` axis also admits `DOCS_WAIVED`; the determination gate in §3.8 accepts either `DOCS_COMPLETE` or `DOCS_WAIVED` for livestock claims.

### 3.8. Loss Determination, Indemnity Payment, and Reserve Accounting

The loss-determination board acts through a `ClaimsApprover`, who submits a `decision` of `APPROVE`, `DENY`, or `PARTIAL`, an `approved_indemnity_cents`, a `denial_reason_code` when denying, and the concurrency field `expected_policy_version` described in §2.8. The request's checks run in a fixed order, after the pipeline checks of §2.9. The claim must be in `UNDER_REVIEW` (`ERR_CLAIM_NOT_IN_UNDER_REVIEW`, HTTP 409). Segregation of duties comes next: the approver's `X-User-ID` must differ from the claim's `adjuster_id` — the adjuster who inspected a loss can never approve it — and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403). For livestock claims the documentation gate follows, applying only to `APPROVE` and `PARTIAL` decisions — a denial is never blocked by it: `doc_posture` must read `DOCS_COMPLETE` or `DOCS_WAIVED`, else the decision is rejected with `ERR_DOCS_INCOMPLETE` (HTTP 422). The fiscal guard runs last: the indemnity base (the provisional on `APPROVE`, the approver's figure on `PARTIAL`) may not exceed the policy's `premium_reserve_cents` plus the claim's `provisional_indemnity_cents` — a safety net against runaway approvals — and a breach is rejected with `ERR_INDEMNITY_EXCEEDS_RESERVE` (HTTP 402).

A denial must carry a `denial_reason_code` drawn from `FRAUD`, `NOT_COVERED_PERIL`, `LATE_NOTICE_OVER_30D`, `MISSING_DOCS`, or `POLICY_INACTIVE`, and it must set `approved_indemnity_cents` to zero; a denial submitted without a reason or with a nonzero amount is rejected with `ERR_INVALID_REQUEST`. The coverage window is enforced at intake only and is not re-evaluated at decision time. Each determination records the deciding approver as `reviewer_id`, is stamped with `decided_at` from the logical clock, and carries its `claim_id`.

When the decision is `APPROVE` or `PARTIAL`, the final indemnity follows a fixed waterfall. For a straight approval the base is the claim's provisional indemnity — the submitted `approved_indemnity_cents` is disregarded on `APPROVE` — while a partial decision substitutes the approver's own figure, which may be lower than the provisional. The waterfall then applies its reductions in pinned order, truncating each intermediate result to whole cents before the next step runs. First comes the `applied_coverage_reduction_pct`, taken from the latest late acreage or head report on the unit — zero when every report was timely — which scales the base down. Second comes the `applied_late_notification_penalty_pct`, copied from the claim, which scales the result down again. Third, when a dual-coverage link exists on the policy, the dual-coverage offset — twenty percent of the federal policy's `liability_cents`, capped at the amount remaining at that step — is subtracted and recorded as `applied_dual_coverage_offset_cents`. Finally the result is floored at zero and rounded half up to whole cents. The outcome is written to the determination's `final_indemnity_cents` and mirrored onto the claim's `final_indemnity_cents`.

Approval cascades widely. The claim moves from `UNDER_REVIEW` to `APPROVED`; the coverage unit settles, moving from `UNDER_CLAIM` to `SETTLED`; the grower's `prior_claims_count` increments by one, which can lift the surcharge tier on future applications; and the policy's `premium_reserve_cents` is recomputed as sixty percent of `premium_cents` rounded down to a whole cent, less the sum of `final_indemnity_cents` across the policy's `APPROVED` and `PAID` claims, floored at zero — with the policy's `version` incrementing as the cascade lands. A denial is quieter: the claim moves to `DENIED` and the unit settles to `SETTLED`, with no reserve or claim-count impact — though issuing a determination of either outcome increments the parent policy's `version`. Approvals also feed the carrier-level reinsurance check: whenever the aggregate of `APPROVED` and `PAID` indemnities across the whole carrier reaches or exceeds the carrier's `reinsurance_treaty_attachment_cents`, the carrier's `reinsurance_posture` reads `ATTACHED` — otherwise `BELOW_ATTACHMENT` — on carrier reads; the posture is an informational observation only and mutates no stored entity.

Payment closes the loop. A claims approver issues the indemnity payment with a `payment_method` of `ACH`, `CHECK`, or `WIRE`; the checks run in a fixed order — first, no payment in a `status` other than `VOID` may already exist for the claim (`ERR_PAYMENT_ALREADY_ISSUED`, HTTP 409), and then the claim must be `APPROVED` (`ERR_CLAIM_NOT_IN_APPROVED`, HTTP 409). The issued payment snapshots its `amount_cents` from the claim's `final_indemnity_cents` at the moment of issue, stamps `issued_at` from the logical clock, records its `claim_id`, begins in `ISSUED` status, and moves the claim from `APPROVED` to `PAID`. A payment that clears is moved from `ISSUED` to `CLEARED`. Alternatively, a payment may be voided within twenty-four hours of its `issued_at`, which moves it to `VOID` and re-opens the claim from `PAID` back to `APPROVED` so a corrected payment can be issued; a void attempted after the twenty-four-hour window is rejected with `ERR_VOID_WINDOW_EXPIRED` (HTTP 422). Clearing or voiding a payment that is not `ISSUED` is rejected with `ERR_INVALID_STATE`.

### 3.9. Renewal, Cancellation, Expiration, and Debarment

When a policy reaches `EXPIRED`, an underwriter decides its future through the renewal workflow, submitting a `decision` of `RENEW` or `NON_RENEW` together with the new period's `effective_date` and `expiration_date` and the concurrency field `expected_prior_policy_version` described in §2.8; a pair whose expiration does not fall after its effective date is rejected with `ERR_INVALID_DATE_RANGE` (HTTP 422). The policy being renewed must be `EXPIRED` and tied to the same grower; anything else is rejected with `ERR_POLICY_NOT_RENEWABLE` (HTTP 409).

On `RENEW`, a brand-new policy is created in `APPLICATION` whose `prior_policy_id` points at the expired policy, with its `continuous_coverage_carryover_credit_cents` computed as §3.4 describes and its surcharge tier read from the grower's current `prior_claims_count`; the grower's `continuous_coverage_since` — null until the first renewal — is then maintained as the start of the earliest un-broken coverage period: when the continuity gap is at most seven days it is set from the prior policy's `effective_date` if still null and otherwise left unchanged, and when the gap exceeds seven days it is (re)set to the new policy's `effective_date`. The renewal record itself stores the new policy as its `policy_id`, the renewed policy as its `prior_policy_id`, the `continuity_gap_days` between the prior expiration and the new effective date — zero when the two periods are contiguous — the computed `carryover_credit_cents`, which is five percent of the prior policy's premium when the gap is at most seven days and the prior policy expired rather than being cancelled, and zero otherwise, the `decision`, and a `decided_at` stamp from the logical clock. On `NON_RENEW`, no new policy is created, the expired policy moves from `EXPIRED` to `NON_RENEWED`, and the renewal record's `policy_id` is null. Either decision increments the prior policy's `version`, which is exactly why the renewal write carries the concurrency guard. A policy's renewal listing returns the records that name the policy either as the new policy or as the prior policy.

Cancellation is the underwriter's other exit. A policy in `BOUND` or `ACTIVE` may be cancelled — cancellation from any other lifecycle state is rejected with `ERR_POLICY_NOT_CANCELLABLE` (HTTP 409) — but not while claims in `INSPECTION_SCHEDULED`, `INSPECTED`, `UNDER_REVIEW`, or `APPROVED` remain open; open claims block the cancellation with `ERR_OPEN_CLAIMS_BLOCK_CANCEL` (HTTP 409). A successful cancellation moves the policy to `CANCELLED`, flips `claims_posture` to `RESTRICTED`, withdraws any claims still sitting in `REPORTED`, zeroes the `premium_reserve_cents`, and increments the policy's `version`. Expiration, by contrast, is the clock's doing: when `current_utc` reaches the `expiration_date`, an `ACTIVE` policy moves to `EXPIRED`, its posture restricts, and any coverage units still `PENDING_REPORT` lapse to `LAPSED_REPORT`.

Debarment is the fraud exit, and it cascades through the whole book. An underwriter may debar a grower whose `status` is `ACTIVE` or `SUSPENDED` — debarring a grower in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409); the grower moves to the terminal `DEBARRED` status, every `BOUND` or `ACTIVE` policy of that grower is cancelled in cascade, and every claim of that grower in `REPORTED` or `INSPECTION_SCHEDULED` is withdrawn in cascade.

## 4. Endpoint Definitions

Operations that create a new resource — a carrier, grower, adjuster, rate-table row, federal crop policy, policy, coverage unit, acreage or head report, claim, field inspection, veterinary report, loss determination, indemnity payment, dual coverage link, renewal, or premium payment — return `201 Created`. Operations that act on an existing resource without creating a new one (bind, cancel, publish, supersede, debar, assign-adjuster, withdraw, submit-for-review, clear, void, and the clock-setting capability) return `200 OK`, as do all reads.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/carriers` | Create a carrier | PlatformAdmin |
| GET | `/carriers/{carrierId}` | Fetch a carrier | PlatformAdmin, Underwriter, Policyholder, Adjuster, ClaimsApprover |
| POST | `/carriers/{carrierId}/_clock/set_current_utc` | Advance the carrier's logical clock | Underwriter |
| POST | `/carriers/{carrierId}/growers` | Register a grower | Underwriter |
| GET | `/carriers/{carrierId}/growers` | List growers | PlatformAdmin, Underwriter, ClaimsApprover |
| GET | `/carriers/{carrierId}/growers/{growerId}` | Fetch a grower | PlatformAdmin, Underwriter, Policyholder, Adjuster, ClaimsApprover |
| POST | `/carriers/{carrierId}/growers/{growerId}/debar` | Debar a grower for fraud | Underwriter |
| POST | `/carriers/{carrierId}/adjusters` | Register an adjuster | Underwriter |
| GET | `/carriers/{carrierId}/adjusters/{adjusterId}` | Fetch an adjuster | PlatformAdmin, Underwriter, Adjuster, ClaimsApprover |
| POST | `/carriers/{carrierId}/rate-tables` | Create a rate-table row | Underwriter |
| GET | `/carriers/{carrierId}/rate-tables` | List rate-table rows | PlatformAdmin, Underwriter, Policyholder, Adjuster, ClaimsApprover |
| GET | `/carriers/{carrierId}/rate-tables/{rateTableId}` | Fetch a rate-table row | PlatformAdmin, Underwriter, Policyholder, Adjuster, ClaimsApprover |
| POST | `/carriers/{carrierId}/rate-tables/{rateTableId}/publish` | Publish a rate-table row | Underwriter |
| POST | `/carriers/{carrierId}/rate-tables/{rateTableId}/supersede` | Supersede a published rate-table row | Underwriter |
| POST | `/carriers/{carrierId}/federal-crop-policies` | Register a federal crop policy | Underwriter |
| GET | `/carriers/{carrierId}/federal-crop-policies` | List federal crop policies | PlatformAdmin, Underwriter, ClaimsApprover |
| GET | `/carriers/{carrierId}/federal-crop-policies/{fciId}` | Fetch a federal crop policy | PlatformAdmin, Underwriter, Policyholder, Adjuster, ClaimsApprover |
| POST | `/carriers/{carrierId}/federal-crop-policies/{fciId}/cancel` | Cancel a federal crop policy | Underwriter |
| POST | `/carriers/{carrierId}/policies` | Create a policy application | Underwriter |
| GET | `/carriers/{carrierId}/policies` | List policies | PlatformAdmin, Underwriter, ClaimsApprover |
| GET | `/carriers/{carrierId}/policies/{policyId}` | Fetch a policy | PlatformAdmin, Underwriter, Policyholder, Adjuster, ClaimsApprover |
| POST | `/carriers/{carrierId}/policies/{policyId}/bind` | Bind a policy application | Underwriter |
| POST | `/carriers/{carrierId}/policies/{policyId}/cancel` | Cancel a bound or active policy | Underwriter |
| POST | `/carriers/{carrierId}/policies/{policyId}/coverage-units` | Add a coverage unit to a policy application | Underwriter |
| GET | `/carriers/{carrierId}/policies/{policyId}/coverage-units` | List coverage units for a policy | PlatformAdmin, Underwriter, Policyholder, Adjuster, ClaimsApprover |
| GET | `/carriers/{carrierId}/policies/{policyId}/coverage-units/{unitId}` | Fetch a coverage unit | PlatformAdmin, Underwriter, Policyholder, Adjuster, ClaimsApprover |
| POST | `/carriers/{carrierId}/policies/{policyId}/coverage-units/{unitId}/acreage-reports` | Submit a planting or harvest acreage report | Policyholder |
| GET | `/carriers/{carrierId}/policies/{policyId}/coverage-units/{unitId}/acreage-reports` | List acreage reports for a coverage unit | PlatformAdmin, Underwriter, Policyholder, Adjuster, ClaimsApprover |
| POST | `/carriers/{carrierId}/policies/{policyId}/coverage-units/{unitId}/head-reports` | Submit an initial, interim, or final head-count report | Policyholder |
| GET | `/carriers/{carrierId}/policies/{policyId}/coverage-units/{unitId}/head-reports` | List head reports for a coverage unit | PlatformAdmin, Underwriter, Policyholder, Adjuster, ClaimsApprover |
| POST | `/carriers/{carrierId}/policies/{policyId}/claims` | File first notice of loss | Policyholder |
| GET | `/carriers/{carrierId}/policies/{policyId}/claims` | List claims for a policy | PlatformAdmin, Underwriter, Policyholder, Adjuster, ClaimsApprover |
| GET | `/carriers/{carrierId}/policies/{policyId}/claims/{claimId}` | Fetch a claim | PlatformAdmin, Underwriter, Policyholder, Adjuster, ClaimsApprover |
| POST | `/carriers/{carrierId}/policies/{policyId}/claims/{claimId}/assign-adjuster` | Assign an adjuster to a reported claim | ClaimsApprover |
| POST | `/carriers/{carrierId}/policies/{policyId}/claims/{claimId}/withdraw` | Withdraw a claim | Policyholder |
| POST | `/carriers/{carrierId}/policies/{policyId}/claims/{claimId}/field-inspections` | Submit a field inspection report | Adjuster |
| GET | `/carriers/{carrierId}/policies/{policyId}/claims/{claimId}/field-inspections` | List field inspections for a claim | PlatformAdmin, Underwriter, Policyholder, Adjuster, ClaimsApprover |
| POST | `/carriers/{carrierId}/policies/{policyId}/claims/{claimId}/submit-for-review` | Forward an inspected claim for review | Adjuster |
| POST | `/carriers/{carrierId}/policies/{policyId}/claims/{claimId}/veterinary-reports` | Submit a veterinary certificate, necropsy report, or affidavit | Policyholder |
| GET | `/carriers/{carrierId}/policies/{policyId}/claims/{claimId}/veterinary-reports` | List veterinary reports for a claim | PlatformAdmin, Underwriter, Policyholder, Adjuster, ClaimsApprover |
| POST | `/carriers/{carrierId}/policies/{policyId}/claims/{claimId}/determinations` | Issue the loss determination | ClaimsApprover |
| GET | `/carriers/{carrierId}/policies/{policyId}/claims/{claimId}/determinations` | List determinations for a claim | PlatformAdmin, Underwriter, ClaimsApprover |
| POST | `/carriers/{carrierId}/policies/{policyId}/claims/{claimId}/indemnity-payments` | Issue the indemnity payment | ClaimsApprover |
| GET | `/carriers/{carrierId}/policies/{policyId}/claims/{claimId}/indemnity-payments` | List indemnity payments for a claim | PlatformAdmin, Underwriter, ClaimsApprover |
| POST | `/carriers/{carrierId}/policies/{policyId}/claims/{claimId}/indemnity-payments/{paymentId}/clear` | Mark a payment cleared | ClaimsApprover |
| POST | `/carriers/{carrierId}/policies/{policyId}/claims/{claimId}/indemnity-payments/{paymentId}/void` | Void a payment within its void window | ClaimsApprover |
| POST | `/carriers/{carrierId}/policies/{policyId}/dual-coverage-links` | Link a private crop-hail policy to a federal crop policy | Underwriter |
| GET | `/carriers/{carrierId}/policies/{policyId}/dual-coverage-links` | List dual coverage links for a policy | PlatformAdmin, Underwriter, ClaimsApprover |
| POST | `/carriers/{carrierId}/policies/{policyId}/renewals` | Renew or non-renew an expired policy | Underwriter |
| GET | `/carriers/{carrierId}/policies/{policyId}/renewals` | List renewals for a policy | PlatformAdmin, Underwriter, ClaimsApprover |
| POST | `/carriers/{carrierId}/policies/{policyId}/premium-payments` | Post a premium payment | Policyholder |
| GET | `/carriers/{carrierId}/policies/{policyId}/premium-payments` | List premium payments for a policy | PlatformAdmin, Underwriter, Policyholder, ClaimsApprover |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_DATE_RANGE` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_POLICY_NOT_IN_APPLICATION` | 409 Conflict |
| `ERR_POLICY_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_POLICY_NOT_RENEWABLE` | 409 Conflict |
| `ERR_POLICY_NOT_BILLABLE` | 409 Conflict |
| `ERR_CLAIM_NOT_IN_REPORTED` | 409 Conflict |
| `ERR_CLAIM_NOT_IN_INSPECTION_SCHEDULED` | 409 Conflict |
| `ERR_CLAIM_NOT_IN_INSPECTED` | 409 Conflict |
| `ERR_CLAIM_NOT_IN_UNDER_REVIEW` | 409 Conflict |
| `ERR_CLAIM_NOT_IN_APPROVED` | 409 Conflict |
| `ERR_CLAIM_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_POLICY_RESTRICTED` | 409 Conflict |
| `ERR_NO_COVERAGE_UNITS` | 422 Unprocessable Entity |
| `ERR_NO_ACTIVE_RATE_TABLE` | 422 Unprocessable Entity |
| `ERR_RATE_TABLE_OVERLAP` | 409 Conflict |
| `ERR_LOSS_DATE_OUT_OF_COVERAGE` | 422 Unprocessable Entity |
| `ERR_LATE_NOTICE_OVER_30D` | 422 Unprocessable Entity |
| `ERR_REPORT_BEFORE_COVERAGE` | 422 Unprocessable Entity |
| `ERR_OPEN_CLAIMS_BLOCK_CANCEL` | 409 Conflict |
| `ERR_ADJUSTER_NOT_ACTIVE` | 409 Conflict |
| `ERR_ADJUSTER_COUNTY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ADJUSTER_SPECIES_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ADJUSTER_CAPACITY_FULL` | 409 Conflict |
| `ERR_NOT_ASSIGNED_ADJUSTER` | 403 Forbidden |
| `ERR_NECROPSY_REQUIRED` | 422 Unprocessable Entity |
| `ERR_DOCS_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
| `ERR_INDEMNITY_EXCEEDS_RESERVE` | 402 Payment Required |
| `ERR_PAYMENT_ALREADY_ISSUED` | 409 Conflict |
| `ERR_VOID_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_DUAL_COVERAGE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_GROWER_NOT_ACTIVE` | 409 Conflict |
