# Hospice & Palliative Care API — Product Requirements Document

## 1. Introduction

Hospice and palliative care reimbursement sits at the intersection of clinical attestation and benefit-period accounting, and the rules that govern it are unforgiving: a terminal-illness prognosis must be re-attested on a fixed 90/90/60 cadence, every day of care is paid at a level-of-care per-diem that itself shifts over the life of the election, and the agency's annual revenue is ultimately constrained by an aggregate per-beneficiary cap that is reconciled at year-end. This document specifies an API that models that entire spell of care as a single auditable object — the **election** — and the satellite records that hang off it: the recurring benefit periods, the physician certifications that open them, the interdisciplinary plan of care, the daily care ledger, the medication and durable-medical-equipment (DME) items billed under the plan, and the bereavement services that follow a death.

The system serves four operational roles whose duties are deliberately segregated: an intake coordinator who enrolls and revokes beneficiaries, a hospice physician who certifies prognosis and performs face-to-face encounters, a clinical manager who owns the plan of care and the day-to-day delivery of care, and a billing administrator who registers the agency and settles its annual cap. Because certification races, lazy materialization of future periods, and a year-end reconciliation that differs subtly from the running estimate are all part of the real domain, the API exposes optimistic-concurrency guards and a test-driving clock so that the full temporal lifecycle — including a benefit period quietly expiring un-recertified — can be exercised deterministically. The sections that follow define the global contract first, then the business workflows, then the endpoint and error references that bind them together.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contract, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); a blank or whitespace-only `X-User-ID`, and an `X-User-Role` whose value is not exactly one of the four recognized role strings, both count as malformed and yield `ERR_UNAUTHENTICATED`. When the headers are well-formed — both present and the role one of the four recognized strings — but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly four roles, spelled precisely as follows: `IntakeCoordinator`, `Physician`, `ClinicalManager`, and `BillingAdmin`. The intake coordinator handles beneficiary election, revocation, and intake-side reads. The physician certifies and recertifies terminal prognosis and conducts face-to-face encounters. The clinical manager owns the interdisciplinary plan of care, posts level-of-care days, adjudicates coverage, discharges elections, manages bereavement, and registers physicians. The billing administrator owns provider registration and the aggregate per-diem cap settlement. The precise allocation of each operation to its authorized roles is given in the endpoint table of §4; both the role-exclusive write operations and the broadly shared read operations follow from that table.

Identity binds to resources differently per role. When `X-User-Role` is `Physician`, `X-User-ID` is the `id` of the acting `Physician` entity; ownership and recognition checks on any resource that references a physician (for example, a certification's `certifying_physician_id` or `face_to_face_physician_id`) compare that foreign-key field to the registered `Physician` population. The other three roles — `IntakeCoordinator`, `ClinicalManager`, and `BillingAdmin` — are opaque operator identifiers not tied to any persisted entity; the server may record the supplied `X-User-ID` for audit purposes but does not compare it to any entity's `id` for ownership.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the start of the result set and defaults to 0, with a minimum of 0 and no upper bound. A `limit` or `offset` outside its permitted bounds, or a value that is not a base-10 integer, is treated as an invalid request and rejected with `ERR_INVALID_REQUEST` (HTTP 400); an offset that exceeds `total_count` is in-bounds and simply returns an empty page.

Unless a specific endpoint states otherwise, list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order, with ties on identical `created_at` timestamps broken by the resources' underlying creation order (the order in which they were minted) so the ordering is fully deterministic. The sole documented exception is the listing of an election's care days, which is ordered by `service_date` ascending, again with ties broken by creation order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `has_more` is true exactly when the offset plus the number of returned items is less than `total_count`.

### 2.4. Common Resource Properties

Every persisted resource in this system carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits marking when the resource was first created. All entities in this domain — `Provider`, `Election`, `BenefitPeriod`, `Certification`, `CarePlan`, `CareDay`, `CoverageItem`, `Physician`, and `BereavementCase` — additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) refreshed on every mutation, and a `version` integer that begins at its initial value of 1 and increments by one on every mutation of that resource. The `version` field is the basis for the optimistic-concurrency mechanism described in §2.7.

Resource identifiers supplied by clients (for instance `provider_id`, `election_id`, `care_plan_id`, `supersedes_plan_id`, `certifying_physician_id`, `face_to_face_physician_id`, and `attending_physician_id`) are opaque strings; the server validates that the referenced resources exist before acting on them.

### 2.5. Hierarchical Reads, Existence Ordering, and Derived-Field Consistency

Many resources are reached through nested paths anchored on a parent election or provider. For any request whose path contains multiple identifiers, the server validates each segment left-to-right and rejects the first missing identifier with `ERR_RESOURCE_NOT_FOUND` (HTTP 404). The same existence check covers foreign-key references inside request bodies: any of `Provider`, `Election`, `BenefitPeriod`, `Certification`, `CarePlan`, `Physician`, or `BereavementCase` named by a path segment or a body field must exist, validated in declaration order, before any business rule is evaluated.

Several fields on the election are **derived** and must be kept consistent with the underlying care-day ledger and the materialized benefit periods. Whenever an election is mutated or read back through its detail endpoint, the server recomputes `current_period_number` and `days_used_in_period`. The `current_period_number` equals the sequence of the benefit period whose nominal window contains the elapsed-day cursor (the difference in days between the current clock and `election_date`), bounded by the highest period materialized so far. The `days_used_in_period` equals the count of care days bound to the current benefit period; here the "current benefit period" is resolved as the benefit period of the latest care day on the election — the day ordered last by `service_date` ascending and then by creation order ascending — and, when the election has no care day yet, falls back to the period matching `current_period_number` (yielding 0 when no such period exists). It is reconciled on every care-day posting and again on revoke and discharge. Each such reconciliation is a mutation of the affected resource that refreshes `updated_at` and increments `version`, but only when the reconciliation actually changes `current_period_number` or `days_used_in_period`; a reconciliation that recomputes the identical values leaves `updated_at` and `version` untouched.

When a parent resource transitions or a derived value changes, the system propagates the consequence immediately rather than waiting for an explicit client action. Most notably, committing a certification or a superseding care plan increments the parent election's `version` by one (see §2.7 and §3), and superseding a care plan flips the prior plan to `SUPERSEDED` in the same operation.

### 2.6. Per-Diem Precision and Monetary Representation

All monetary amounts in this system — the statutory cap `per_beneficiary_cap_cents`, the per-day `payment_cents`, and the provider ledger fields `total_paid_cents`, `cap_liability_cents` — are integer counts of cents. The per-diem rate table is expressed in whole-cent constants, so per-day pricing involves no rounding: a day's `payment_cents` is exactly the applicable rate constant. Aggregations (the running and final cap computations) are integer-cent sums and differences and likewise require no rounding. No monetary value is ever represented as a fractional-cent or floating-point quantity.

### 2.7. Optimistic Concurrency on the Election

Two write operations advance the election and therefore guard against acting on a stale view of it: committing a certification and creating a care plan. Both require a non-optional `expected_election_version` field in their request body, carrying the `version` of the target `Election` the client last observed.

For a certification commit, the request must carry `expected_election_version` equal to the target election's current `version`. If another writer has already certified the same pending period — legitimately advancing the election and materializing the next period — the election's `version` will have moved past the client's observed value, the client's notion of which period is pending is stale, and the commit is rejected with `ERR_STALE_ELECTION_VERSION` (HTTP 412). For a care-plan create, the request must likewise carry `expected_election_version` equal to the election's current `version`; if another writer has already committed a revision that superseded the same prior plan, the supersede target is no longer active and the client's election view is stale, so the create is rejected with `ERR_STALE_ELECTION_VERSION` (HTTP 412). No other endpoint takes a version field; only these two writes carry `expected_election_version`, and only they perform the stale-version check.

## 3. Business Logic & Workflows

### 3.1. Provider Registration and the Annual Cap Window

A `BillingAdmin` registers a hospice agency by supplying its legal `name`, a `cap_year_start`, and the statutory `per_beneficiary_cap_cents`. The `name` must be non-empty. The `cap_year_start` is an ISO 8601 UTC-midnight datetime that anchors the agency's annual cap accounting year; the cap window runs from `cap_year_start` inclusive to the instant 365 days later, exclusive. The `per_beneficiary_cap_cents` is the per-beneficiary aggregate cap amount for that year, in cents (for example, a value of 3490000 represents a $34,900.00 cap), and must be zero or greater.

At registration the provider's computed ledger is initialized to a clean slate: `cap_liability_cents`, `total_paid_cents`, and `counted_beneficiaries` all begin at 0, and `cap_settled` begins false. The `cap_settled` flag records whether the cap year has been finalized; while it remains false the year is in progress, and once it flips true no further care days may be posted into the settled window.

### 3.2. Electing the Hospice Benefit and Materializing Period 1

An `IntakeCoordinator` elects the hospice benefit for a beneficiary by submitting the owning `provider_id`, the beneficiary's `patient_name` (which must be non-empty), the `election_date`, and the `attending_physician_id`. The `election_date` is the effective first day of benefit period 1 and must be an ISO 8601 UTC-midnight datetime; it serves as day one of the entire spell of care. The `attending_physician_id` is an opaque string identifying the patient's chosen attending physician of record — it may coincide with a certifying physician's user id or name an external physician, and is stored as a plain string rather than a validated foreign key. Election is refused, with `ERR_CAP_YEAR_SETTLED` (HTTP 409), when the named provider is settled and the `election_date` falls inside that provider's 365-day cap window (`cap_year_start` inclusive to 365 days later exclusive).

A new election begins in `ELECTED` status. Creation immediately materializes the first benefit period: a `BenefitPeriod` with `sequence` equal to 1, `length_days` equal to 90, `start_offset_days` equal to 0, and `cert_status` equal to `PENDING_CERT`. The election's `current_period_number` is set to 1 and `days_used_in_period` to 0. The election also carries a `revocation_date`, which is null while the patient remains `ELECTED`, and a `bereavement_required` flag, which begins false. Later benefit periods are not created up front; they are materialized lazily, one at a time, as each certification is committed.

The four lifecycle exits from `ELECTED` are revocation, discharge, expiry, and — only as an internal posture — staying elected across further certifications. The status enumeration for an election is exactly `ELECTED`, `REVOKED`, `DISCHARGED`, and `EXPIRED`.

### 3.3. The 90/90/60 Benefit-Period Cadence

Benefit periods follow a fixed cadence keyed solely on their one-based `sequence`. The first and second periods are each 90 days long; the third period and every period thereafter are 60 days long. Accordingly a period's nominal `length_days` is 90 when its `sequence` is 1 or 2, and 60 otherwise. Each period's `start_offset_days` is the sum of the nominal lengths of all earlier periods: period 1 starts at offset 0, period 2 at offset 90, period 3 at offset 180, period 4 at offset 240, period 5 at offset 300, and so on, each later offset being the previous offset plus the previous period's length. These offsets and lengths always use the nominal 90/90/60 figures regardless of how many care days were actually delivered.

A period's `requires_face_to_face` flag is computed: it is true for any period whose `sequence` is 3 or greater — the recertification face-to-face encounter is mandatory before the third and each subsequent period — and false for periods 1 and 2. Each period also tracks the `certification_id` that opened it, which stays null until a certification is recorded against it, and a `cert_status` that is one of `PENDING_CERT` or `CERTIFIED`, beginning at `PENDING_CERT`.

The election's `current_period_number` is derived from an elapsed-day cursor rather than from nominal offsets alone: walking forward from period 1, the cursor advances into period *n+1* only once the elapsed days since `election_date` reach that next period's `start_offset_days`, and never past the highest period materialized so far. Because the cursor reflects the real clock, it can fall short of the nominal schedule when a patient revokes early.

### 3.4. Certification, Recertification, and the Face-to-Face Encounter

Before any certification can name a physician, that physician must be on file. A `ClinicalManager` registers a hospice physician by supplying a non-empty `full_name` and an optional `is_medical_director` flag, which defaults to false and marks whether the physician may serve as the hospice medical director and thus as sole certifier of an initial certification.

Certification is the act by which a `Physician` attests a prognosis of six months or less and opens the next benefit period. A certification names the `election_id` being certified, the `period_sequence` it attests, the `certifying_physician_id` (the hospice physician or medical director attesting the prognosis), and a `narrative_present` flag indicating whether the physician composed the required clinical narrative. It also carries `expected_election_version` for the concurrency guard, and an optional `commit` flag distinguishing a draft from a committed certification, which defaults to true (a committed certification) when omitted or null. A certification's own `status` is one of `DRAFT`, `CERTIFIED`, or `REJECTED`, beginning at `DRAFT`; when it is rejected, a `rejection_reason` is populated, and it is null otherwise.

The `period_sequence` submitted must equal the election's lowest benefit period still in `PENDING_CERT`. Certifying out of order, or attempting to re-certify a period already `CERTIFIED`, is rejected with `ERR_PERIOD_SEQUENCE_MISMATCH` (HTTP 409). A certification with `commit` false is persisted in `DRAFT` against that pending period and returned with `201 Created`; this draft mode exists so that a second physician can co-sign an initial certification before it is committed. Draft creation still requires the period-sequence match above and the existence checks, but it evaluates none of the certify preconditions (narrative, medical-director/two-physician backing, or face-to-face window) and performs no optimistic-concurrency check, so a draft is persisted even when its `expected_election_version` does not match the election's current `version`; the election's `version` is left unchanged by a draft.

Whether a committed certification ends up `CERTIFIED` or `REJECTED` depends on the certify preconditions, which branch on the period. For an initial period — `period_sequence` of 1 or 2 — the certification must carry a clinical narrative (`narrative_present` true) and must be backed either by a certifying physician who is a medical director or by a second certification from a distinct physician for the same `period_sequence` (the two-physician initial certification) — where that second certification is any other already-persisted certification for the same `election_id` and `period_sequence` whose `certifying_physician_id` differs from this one, counted regardless of that other certification's own `status` (a `DRAFT`, `CERTIFIED`, or `REJECTED` co-signature all satisfy the condition). If the narrative is absent, or neither the medical-director nor the two-physician condition holds, the commit is rejected with `ERR_CERTIFICATION_INCOMPLETE` (HTTP 422). For the third and every later period — `period_sequence` of 3 or greater — the certification additionally requires a `face_to_face_physician_id` and a `face_to_face_date`: the encounter physician must be a recognized hospice physician, and the `face_to_face_date` must fall within the 30 days immediately before that period's start (the window ending at the period's `start_offset_days`). Concretely, with the period start anchored at `election_date` plus `start_offset_days`, the valid window runs from 30 days before that start through the start itself, with both endpoints inclusive (`election_date + start_offset_days − 30 days <= face_to_face_date <= election_date + start_offset_days`). When the face-to-face physician or date is missing, or the date falls outside that 30-day pre-period window, the commit is rejected with `ERR_FACE_TO_FACE_REQUIRED` (HTTP 422). Both `face_to_face_physician_id` and `face_to_face_date` may be null for periods 1 and 2.

When all certify preconditions hold and `expected_election_version` matches, the commit succeeds: the target period's `cert_status` becomes `CERTIFIED` and its `certification_id` is set to this certification, the certification's own `status` becomes `CERTIFIED`, the next benefit period (one sequence higher) is materialized in `PENDING_CERT` with its `length_days` and `start_offset_days` computed per the 90/90/60 rule, and the election's `version` is incremented by one. The election itself remains `ELECTED` throughout. When a precondition fails — the narrative absent, or a sequence-3-or-later face-to-face window unmet — the commit takes the reject branch: the certification's `status` becomes `REJECTED` with a `rejection_reason` (the certification record is persisted in this rejected state), the period stays `PENDING_CERT`, no new period is materialized, and the election's `version` is left unchanged. The HTTP response for a rejected commit is the corresponding failure error rather than a `201 Created` success carrying the rejected certification: `ERR_FACE_TO_FACE_REQUIRED` (HTTP 422) when the sequence-3-or-later face-to-face requirement is unmet, and otherwise `ERR_CERTIFICATION_INCOMPLETE` (HTTP 422) when the narrative is absent or the medical-director/two-physician backing is missing. A draft that fails a precondition at commit likewise transitions from `DRAFT` to `REJECTED`.

### 3.5. The Interdisciplinary Plan of Care

The interdisciplinary plan of care is owned by a `ClinicalManager`. A `CarePlan` is created against an `election_id` and lists its `idg_members` — the discipline codes present at the plan meeting, each drawn from the set `PHYSICIAN`, `NURSE`, `SOCIAL_WORK`, `COUNSELOR`, `AIDE`, and `VOLUNTEER`. The list must include all four core disciplines `PHYSICIAN`, `NURSE`, `SOCIAL_WORK`, and `COUNSELOR`; a plan whose `idg_members` is missing any of these four is rejected with `ERR_IDG_INCOMPLETE` (HTTP 422). An `idg_members` that is not an array, or that contains any value outside the six recognized discipline codes, is instead a structural failure rejected with `ERR_INVALID_REQUEST` (HTTP 400), and this structural check precedes the core-completeness check. The plan also carries a `review_due_offset_days`, the calendar interval after the plan's creation at which the next mandatory interdisciplinary review falls due, which defaults to 15 and must be at least 1. A plan's `status` is one of `ACTIVE` or `SUPERSEDED` and begins `ACTIVE`, while its `revision_number` records its place in the revision chain.

Care plans revise cyclically. The first plan for an election carries a null `supersedes_plan_id` and `revision_number` equal to 1, and may only be created when no other `ACTIVE` plan exists for that election; an attempt to create such a first plan while an `ACTIVE` plan already exists for the election is rejected with `ERR_STALE_ELECTION_VERSION` (HTTP 412). A revision names the prior `ACTIVE` plan it replaces through its `supersedes_plan_id` (a self-reference into the care-plan set); when the named `supersedes_plan_id` does not resolve to an `ACTIVE` plan of this same election — because it is already `SUPERSEDED` or belongs to a different election — the create is likewise rejected with `ERR_STALE_ELECTION_VERSION` (HTTP 412). This supersede-target check is evaluated before the `expected_election_version` comparison, so both the stale-target and the stale-version cases surface as `ERR_STALE_ELECTION_VERSION`. When a revision is committed, the named prior plan transitions from `ACTIVE` to `SUPERSEDED` and the new plan's `revision_number` becomes the prior plan's revision number plus one. Coverage items already ordered under a now-superseded plan stay `COVERED` as historical records. Every care-plan create also requires `expected_election_version` to match the election's current `version` and, on success, increments that `version` by one, as described in §2.7.

### 3.6. Posting Days of Care and the Per-Diem Rate Table

A `ClinicalManager` records each day of care by posting a `CareDay` naming the `election_id`, the `service_date` (an ISO 8601 UTC-midnight datetime), the `level_of_care`, and an optional `high_intensity` flag that defaults to false when omitted or null. The `level_of_care` is one of `ROUTINE`, `RESPITE`, or `GIP`. The server binds the day to its benefit period — the `benefit_period_id` is resolved from the `service_date` to the materialized period whose nominal window (from its `start_offset_days` up to but not including its `start_offset_days` plus `length_days`) contains the day, measured by the day's elapsed-day index from `election_date`, and is left null when no materialized period's window contains the day — computes the day's `payment_cents`, computes the `respite_run_length`, reconciles the election's `days_used_in_period`, and recomputes the provider's cap ledger.

The per-diem `payment_cents` comes from the level-of-care rate table. A `RESPITE` day pays 47000 cents ($470.00) for inpatient respite. A `GIP` day pays 110000 cents ($1,100.00) for general inpatient care. A `ROUTINE` day is priced on a two-tier service-intensity structure keyed on the day's elapsed position, where the elapsed-day index is the difference in days between the `service_date` and the `election_date` (zero-based, so the election date itself is index 0). The first 60 elapsed days of the election — those whose elapsed-day index is less than 60 — are the high-intensity tier and pay 21000 cents ($210.00); from day 61 onward — elapsed-day index of 60 or greater — the routine day pays the base rate of 16500 cents ($165.00).

The `high_intensity` flag is a `ROUTINE`-only marker for that high tier and must agree with the elapsed-day window. A `high_intensity` of true is valid only when the elapsed-day index is less than 60; a `high_intensity` of false on a `ROUTINE` day is valid only when the elapsed-day index is 60 or greater; and a non-`ROUTINE` day must carry `high_intensity` false. Any disagreement — the flag set true outside the first-60-day window, set false inside it on a routine day, or set true on a respite or GIP day — is rejected with `ERR_INTENSITY_FLAG_MISMATCH` (HTTP 422).

### 3.7. Care-Day Temporal Rules and the Respite Run Limit

A day of care must fall within the active span of the election. The `service_date` must be on or after the `election_date` and strictly before any revocation or discharge date; a date before the election begins, or on or after the day the election terminates, is rejected with `ERR_SERVICE_DATE_OUT_OF_RANGE` (HTTP 422). At most one care day may exist per calendar day per election; a second posting on a `service_date` already used by that election is rejected with `ERR_DUPLICATE_CARE_DAY` (HTTP 409). No care day may be posted into a provider cap year that has already been settled; such a posting is rejected with `ERR_CAP_YEAR_SETTLED` (HTTP 409). This settled-window guard fires only when the provider's `cap_settled` is true and the `service_date` falls inside that provider's 365-day cap window (`cap_year_start` inclusive to 365 days later exclusive); a care day whose `service_date` lies outside the settled window is not blocked by this guard even when the provider is settled.

For respite days the system tracks a consecutive-day run. The `respite_run_length` of a posted `RESPITE` day is the count of consecutive respite days ending on that day, counting the day itself as 1 and walking backward one calendar day at a time so long as the immediately preceding calendar day also has a `RESPITE` care day for the same election; the run is broken by any non-respite day or any calendar gap. When two care days share a `service_date` the ordering for this walk is by `service_date` ascending and then by `created_at` ascending as the deterministic tie-break. For non-respite days the `respite_run_length` is 0. Respite care is capped at 5 consecutive days: a `RESPITE` posting that would produce a run longer than 5 days is rejected with `ERR_RESPITE_LIMIT_EXCEEDED` (HTTP 422).

### 3.8. Medication and DME Coverage

Under an active plan of care, a `ClinicalManager` orders covered items — medications and durable medical equipment. A `CoverageItem` names its `election_id`, the governing `care_plan_id`, the `item_type` (one of `MEDICATION` or `DME`), and a `related_to_terminal_dx` flag. The named `care_plan_id` must reference an `ACTIVE` care plan belonging to the same election; a reference to a plan that is not active, or that belongs to a different election, is rejected with `ERR_PLAN_NOT_ACTIVE` (HTTP 409). Coverage adjudication then sets the item's `coverage_status`: an item is `COVERED` when, and only when, its `related_to_terminal_dx` is true. Items unrelated to the terminal diagnosis and its related conditions are not covered by the hospice benefit; an order whose `related_to_terminal_dx` is false is rejected with `ERR_ITEM_NOT_COVERED` (HTTP 422) rather than being persisted. The `coverage_status` enumeration is `COVERED` or `EXCLUDED`, but because an uncovered order is rejected outright, every persisted `CoverageItem` carries `coverage_status` equal to `COVERED`; the `EXCLUDED` value never appears on a stored item.

### 3.9. Revocation, Discharge, and Expiry

Three operations terminate an active election, each guarded by the requirement that the election currently be `ELECTED`; attempting any of them — like attempting any certify, care-day, care-plan, or coverage-item write — against an election that is already `REVOKED`, `DISCHARGED`, or `EXPIRED` is rejected with `ERR_ELECTION_NOT_ELECTED` (HTTP 409).

An `IntakeCoordinator` revokes an election by supplying a `revocation_date`, which must be on or after the `election_date` and on or after the `service_date` of the latest care day; a `revocation_date` earlier than either bound is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Revocation sets `status` to `REVOKED`, records the `revocation_date`, and forfeits the remainder of the current benefit period with no compensation for already-paid care days; because revocation is not a death, `bereavement_required` stays false. The beneficiary keeps any future periods for a possible later re-election, but this election instance is terminal.

A `ClinicalManager` discharges an election by supplying a `discharge_date` and a `discharge_reason`, where the reason is one of `DEATH`, `MOVED_OUT_OF_AREA`, or `NO_LONGER_TERMINAL`, and the discharge date must be on or after the `service_date` of the latest care day; a `discharge_date` earlier than that bound is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Discharge sets `status` to `DISCHARGED` and records the discharge date as the election's `revocation_date`. Only a `DEATH` discharge sets `bereavement_required` to true and thereby opens bereavement eligibility; a `MOVED_OUT_OF_AREA` or `NO_LONGER_TERMINAL` discharge leaves it false, and after a `NO_LONGER_TERMINAL` discharge the current period's certification posture no longer matters going forward.

Expiry is automatic and driven by the clock rather than by a user request. When the logical clock advances past the end of the highest `CERTIFIED` period of an `ELECTED` election while the next period is still `PENDING_CERT`, that election's `status` becomes `EXPIRED`; coverage lapses when a period ends un-recertified. Precisely, with the highest `CERTIFIED` period spanning elapsed-day indices `[start_offset_days, start_offset_days + length_days)`, expiry fires once the elapsed-day cursor (whole-day difference between the clock and `election_date`) reaches or exceeds that period's end offset `start_offset_days + length_days` — i.e. once the cursor lands on the first day beyond the certified window — and the election's lowest `PENDING_CERT` period sits at a higher sequence than that certified period. The trigger is anchored on the highest `CERTIFIED` period, so it presupposes that at least one period has already been certified: an election that has no `CERTIFIED` period at all — for instance one whose period 1 has lapsed while still `PENDING_CERT`, never having been certified — has no highest `CERTIFIED` period to measure against and is therefore not expired by this rule; it remains `ELECTED` even after that un-certified period's nominal window has elapsed. An expiry leaves `bereavement_required` false.

### 3.10. Bereavement Services

When an election has been discharged by death, its family becomes eligible for bereavement services, opened by a `ClinicalManager`. A `BereavementCase` names the discharged `election_id`, an `enrolled_date` marking when bereavement services begin, and a `service_window_days` giving the length of the bereavement service window, which defaults to 365 and must be at least 365 (the statutory minimum). The case `status` is one of `OPEN` or `CLOSED` and begins `OPEN`.

A bereavement case may be opened only when the referenced election is `DISCHARGED` with `bereavement_required` true — that is, only death discharges qualify — and only when no `OPEN` bereavement case already exists for that election; a request against an election that is not a death discharge, or that already has an open case, is rejected with `ERR_BEREAVEMENT_NOT_ELIGIBLE` (HTTP 409). The `enrolled_date` must be on or after the election's discharge date (its `revocation_date`); an earlier `enrolled_date` is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and this date-bound check is evaluated after the death-discharge and no-open-case eligibility checks above. A clinical manager later closes a case, transitioning an `OPEN` case to `CLOSED`; the close action accepts any current status and sets the case to `CLOSED` (a case already `CLOSED` is simply set to `CLOSED` again).

### 3.11. The Aggregate Per-Diem Cap: Provisional Estimate and Final Settlement

The agency's annual revenue is bounded by an aggregate per-beneficiary cap, and the system maintains a running estimate of it on the provider, recomputed on every care-day posting and recoverable on demand through the provider's cap-summary read. The running estimate is the **provisional** variant. This provisional recompute updates the provider's `total_paid_cents`, `counted_beneficiaries`, and `cap_liability_cents` in place without refreshing the provider's `updated_at` or incrementing its `version`; only the settlement operation (below) advances the provider's `version`. While the cap year is settled, the provisional recompute is suppressed so the frozen figures are not overwritten. The provider's `total_paid_cents` is the sum of `payment_cents` across every care day of every election under that provider whose `service_date` falls inside the current cap window of 365 days. The `counted_beneficiaries` is the number of distinct elections under the provider that have at least one care day inside that window. The cap allowance is the `per_beneficiary_cap_cents` multiplied by `counted_beneficiaries`, and the provisional `cap_liability_cents` is that total paid minus the allowance, but never below zero. Because the allowance grows each time a fresh beneficiary first receives care, the provisional liability is a moving estimate that can actually fall when a new beneficiary is added.

Settlement freezes the year. When a `BillingAdmin` settles a provider's cap, the system performs the **final** variant on a frozen snapshot of all in-window care days taken at the settlement instant and then sets `cap_settled` to true. The final computation differs from the running estimate in one deliberate respect: before summing, each individual beneficiary's in-window payments are first individually capped at the `per_beneficiary_cap_cents` (the streamlined per-beneficiary cap), so that a single heavy general-inpatient user cannot inflate the aggregate beyond that beneficiary's own cap — a treatment the provisional estimate does not apply, since it sums each beneficiary's raw payments. This per-beneficiary-capped sum is what the settlement freezes as `total_paid_cents`. The allowance remains the `per_beneficiary_cap_cents` times the counted beneficiaries, and the demand recorded as the frozen `cap_liability_cents` is the in-window total less the allowance, never below zero — where that "in-window total" is the raw uncapped sum of every in-window care day's `payment_cents` (the same raw aggregate the provisional estimate uses), not the per-beneficiary-capped `total_paid_cents`. The frozen `cap_liability_cents` is therefore computed from the raw aggregate even though the frozen `total_paid_cents` it is reported alongside is the per-beneficiary-capped figure, and the two need not satisfy `cap_liability_cents == total_paid_cents - allowance`. Once settled, the frozen `total_paid_cents`, `counted_beneficiaries`, and `cap_liability_cents` never change again, and the divergence between the live provisional figure read before settlement and the immutable settled demand is the expected consequence of freezing versus live recomputation. A settlement attempt against a cap year already settled is rejected with `ERR_CAP_YEAR_SETTLED` (HTTP 409).

### 3.12. The Test-Driving Clock

Because expiry and the elapsed-day cursors depend on wall-clock time, the system exposes an administrative test-driving capability that sets the server's current UTC clock to a supplied `to_iso8601` instant. Advancing the clock recomputes the elapsed-day cursors that drive `current_period_number` and the routine per-diem tier, and auto-transitions to `EXPIRED` any `ELECTED` election whose highest `CERTIFIED` period has ended while its next period remains `PENDING_CERT`. This capability is available to the `IntakeCoordinator`, `ClinicalManager`, and `BillingAdmin` roles.

### 3.13. Validation Precedence

When more than one rule could reject a request, the checks are evaluated in a fixed precedence so that the returned error is deterministic. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of every path and foreign-key resource validated left-to-right (`ERR_RESOURCE_NOT_FOUND`). After those, the election-state precondition is checked for certify, care-day, care-plan, coverage-item, revoke, and discharge operations (`ERR_ELECTION_NOT_ELECTED`), followed by the cap-year-settled guard for care-day postings and settlement (`ERR_CAP_YEAR_SETTLED`).

The domain-specific checks then follow in order. For certification: the period-sequence match (`ERR_PERIOD_SEQUENCE_MISMATCH`) is evaluated before the face-to-face requirement for third-and-later periods (`ERR_FACE_TO_FACE_REQUIRED`), which is evaluated before the initial-certification completeness check (`ERR_CERTIFICATION_INCOMPLETE`). For care-plan creation, the interdisciplinary-group completeness check applies (`ERR_IDG_INCOMPLETE`). For coverage items, the terminal-diagnosis coverage check (`ERR_ITEM_NOT_COVERED`) precedes the active-plan reference check (`ERR_PLAN_NOT_ACTIVE`). For care-day postings the order is service-date range (`ERR_SERVICE_DATE_OUT_OF_RANGE`), then the respite consecutive-day limit (`ERR_RESPITE_LIMIT_EXCEEDED`), then the intensity-flag agreement (`ERR_INTENSITY_FLAG_MISMATCH`), then the one-day-per-calendar-day uniqueness check (`ERR_DUPLICATE_CARE_DAY`). The bereavement-eligibility check guards case creation (`ERR_BEREAVEMENT_NOT_ELIGIBLE`). The optimistic-concurrency stale-version check on certify and care-plan writes (`ERR_STALE_ELECTION_VERSION`) sits after the preceding domain checks. The structural request check — required fields present and well-typed, enum values within their declared sets, and pagination parameters within bounds (`ERR_INVALID_REQUEST`) — backstops every operation.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that fetch, list, or modify the state of an existing resource — including revoke, discharge, settle-cap, close, and the test-driving clock — return `200 OK`. Every list endpoint accepts the `limit` and `offset` pagination parameters described in §2.3; filterable list endpoints additionally accept the query parameters noted in their description.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/hospice/providers` | Register a hospice provider with its annual aggregate cap parameters | BillingAdmin |
| GET | `/hospice/providers/{id}` | Fetch a provider | BillingAdmin, IntakeCoordinator, ClinicalManager |
| GET | `/hospice/providers/{id}/cap-summary` | Computed read of the provisional aggregate cap liability for the current cap year | BillingAdmin |
| POST | `/hospice/providers/{id}/settle-cap` | Finalize and freeze the cap-year liability; sets `cap_settled` true | BillingAdmin |
| GET | `/hospice/providers/{id}/elections` | List elections under a provider | BillingAdmin, IntakeCoordinator, ClinicalManager |
| POST | `/hospice/physicians` | Register a hospice physician | ClinicalManager |
| GET | `/hospice/physicians/{id}` | Fetch a physician | ClinicalManager, Physician |
| POST | `/hospice/elections` | Elect the hospice benefit for a beneficiary; materializes benefit period 1 | IntakeCoordinator |
| GET | `/hospice/elections/{id}` | Fetch an election with recomputed period fields | IntakeCoordinator, ClinicalManager, Physician, BillingAdmin |
| GET | `/hospice/elections` | List elections; filterable by `provider_id` | IntakeCoordinator, ClinicalManager, BillingAdmin |
| POST | `/hospice/elections/{id}/revoke` | Beneficiary revokes the election; forfeits the remainder of the current period | IntakeCoordinator |
| POST | `/hospice/elections/{id}/discharge` | Discharge the election (death, moved, or no-longer-terminal) | ClinicalManager |
| GET | `/hospice/elections/{id}/benefit-periods` | List benefit periods of an election | IntakeCoordinator, ClinicalManager, Physician, BillingAdmin |
| GET | `/hospice/benefit-periods/{id}` | Fetch a single benefit period | IntakeCoordinator, ClinicalManager, Physician, BillingAdmin |
| GET | `/hospice/benefit-periods` | List benefit periods; filterable by `election_id` or `certification_id` | IntakeCoordinator, ClinicalManager, Physician, BillingAdmin |
| POST | `/hospice/certifications` | Record a certification draft or commit; certify or reject the pending period | Physician |
| GET | `/hospice/certifications/{id}` | Fetch a certification | Physician, ClinicalManager |
| GET | `/hospice/elections/{id}/certifications` | List certifications of an election; filterable by `period_sequence` | Physician, ClinicalManager, BillingAdmin |
| GET | `/hospice/certifications` | List certifications; filterable by `certifying_physician_id`, `face_to_face_physician_id`, or `election_id` | Physician, ClinicalManager, BillingAdmin |
| POST | `/hospice/care-plans` | Create or revise the interdisciplinary plan of care | ClinicalManager |
| GET | `/hospice/care-plans/{id}` | Fetch a care plan revision | ClinicalManager, Physician, BillingAdmin |
| GET | `/hospice/elections/{id}/care-plans` | List care plan revisions of an election; filterable by `status` | ClinicalManager, Physician, BillingAdmin |
| GET | `/hospice/care-plans` | List care plans; filterable by `supersedes_plan_id`, `election_id`, or `status` | ClinicalManager, Physician, BillingAdmin |
| POST | `/hospice/care-days` | Post a day of care at a level of care; computes per-diem and reconciles ledgers | ClinicalManager |
| GET | `/hospice/care-days/{id}` | Fetch a care day | ClinicalManager, BillingAdmin |
| GET | `/hospice/elections/{id}/care-days` | List care days of an election, ordered by `service_date`; filterable by `level_of_care` | ClinicalManager, BillingAdmin |
| GET | `/hospice/care-days` | List care days; filterable by `election_id`, `benefit_period_id`, or `level_of_care` | ClinicalManager, BillingAdmin |
| POST | `/hospice/coverage-items` | Order a medication or DME item under an active care plan | ClinicalManager |
| GET | `/hospice/coverage-items/{id}` | Fetch a coverage item | ClinicalManager, BillingAdmin |
| GET | `/hospice/elections/{id}/coverage-items` | List coverage items of an election; filterable by `item_type` | ClinicalManager, BillingAdmin |
| GET | `/hospice/care-plans/{id}/coverage-items` | List coverage items ordered under a care plan revision | ClinicalManager, BillingAdmin |
| POST | `/hospice/bereavement-cases` | Open a bereavement case for a death-discharged election's family | ClinicalManager |
| GET | `/hospice/bereavement-cases/{id}` | Fetch a bereavement case | ClinicalManager |
| POST | `/hospice/bereavement-cases/{id}/close` | Close a bereavement case | ClinicalManager |
| GET | `/hospice/elections/{id}/bereavement-cases` | List bereavement cases of an election | ClinicalManager, BillingAdmin |
| POST | `/_clock/set_current_utc` | Test-driving endpoint: set the server's current UTC clock and trigger expiry auto-transitions | BillingAdmin, IntakeCoordinator, ClinicalManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_ELECTION_NOT_ELECTED` | 409 |
| `ERR_CAP_YEAR_SETTLED` | 409 |
| `ERR_PERIOD_SEQUENCE_MISMATCH` | 409 |
| `ERR_FACE_TO_FACE_REQUIRED` | 422 |
| `ERR_CERTIFICATION_INCOMPLETE` | 422 |
| `ERR_IDG_INCOMPLETE` | 422 |
| `ERR_ITEM_NOT_COVERED` | 422 |
| `ERR_PLAN_NOT_ACTIVE` | 409 |
| `ERR_SERVICE_DATE_OUT_OF_RANGE` | 422 |
| `ERR_RESPITE_LIMIT_EXCEEDED` | 422 |
| `ERR_INTENSITY_FLAG_MISMATCH` | 422 |
| `ERR_DUPLICATE_CARE_DAY` | 409 |
| `ERR_BEREAVEMENT_NOT_ELIGIBLE` | 409 |
| `ERR_STALE_ELECTION_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |
