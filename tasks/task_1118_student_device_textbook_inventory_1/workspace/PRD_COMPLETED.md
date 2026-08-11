# Student Device & Textbook Inventory API — Product Requirements Document

## 1. Introduction

A district running a 1:1 program hands every student a computing device — and often a set of textbooks — and then spends the rest of the school year answering deceptively simple questions: who is holding which asset, in what condition, and who pays when something goes wrong. This document specifies an API for operating that program end to end. It governs asset intake with barcode and serial tracking, assignment of units to students, a damage and loss fee schedule with an optional annual insurance plan, a repair depot backed by a finite loaner pool, summer collection with re-imaging, end-of-life refresh through disposal or donation, and periodic inventory audits that reconcile the physical fleet against the record so that unaccounted assets can be written off.

Two commitments shape the design. First, equity: a guardian signs an acceptable-use family agreement before any asset moves, students eligible for free lunch receive automatic fee reductions and waivers, and every assessed fee can be appealed. Second, accountability: each student's financial posture is derived continuously from their open fees and gates new obligations, while every meaningful moment in an asset's life is preserved in an immutable lifecycle event trail so the district can reconstruct exactly what happened to any unit — even after it has left service. All resources are mounted under the `/api` prefix, and all operations run against a deterministic logical clock so that time-driven transitions are reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that hold across the entire API: authentication, response envelopes, pagination, identifier formats, monetary precision, concurrency control, the logical clock, the asset event trail, and the order in which validations fire.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. A request missing either header, or presenting a role outside the declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly four roles. `DistrictAdmin` is the district IT administrator — the superset role that owns program lifecycle, fleet creation, end-of-life and disposal decisions, fee adjudication, audit sweeps, and the logical clock. `Registrar` is the school registrar, who enrolls students, checks assets out to them, and declares losses. `SiteTechnician` is the site-level technician, who intakes units, runs the repair depot and loaner pool, processes returns, and confirms or dismisses damage reports. `Family` is a student's guardian, who signs the family agreement, purchases and manages insurance, files damage reports, and appeals fees. A caller whose role is not permitted to invoke an endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403); §4 enumerates the authorized roles for every endpoint.

Identity semantics differ by role, and they determine what `X-User-ID` means. When `X-User-Role` is `DistrictAdmin`, `Registrar`, or `SiteTechnician`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. When `X-User-Role` is `Family`, `X-User-ID` is the `id` of the acting `StudentAccount`; ownership checks on any resource that references a `StudentAccount` compare the resource's foreign-key field to `X-User-ID`. In practice this scopes a guardian to their own student: student-scoped reads and writes require the `studentId` in the path to equal `X-User-ID`.

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
- Requests that match no route are rejected with `ERR_NOT_FOUND` (HTTP 404); a recognized path invoked with the wrong method is rejected with `ERR_INVALID_REQUEST` (HTTP 405); an unexpected server failure surfaces as `ERR_INTERNAL` (HTTP 500).

### 2.3. Pagination

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, and a supplied value outside the range 1 to 100 is clamped to that range rather than rejected. The `offset` parameter skips that many items from the front of the result set and defaults to 0; a negative `offset` is clamped to 0. A non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless a section states otherwise, every list endpoint returns resources sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Program Hierarchy and Nested Resource Retrieval

A **DistrictProgram** is the root container for a school year of the 1:1 program. Fleets and their individual units live beneath it, as do students and everything attached to a student — the family agreement, insurance policies, assignments and their damage reports, fees, and loaner checkouts — and so do the district's audit sweeps. Nested URLs are validated strictly left to right: `progId` first, then the next segment's identifier such as `fleetId`, `studentId`, or `assetId`, and then deeper identifiers such as `assignmentId`, `reportId`, `feeId`, `checkoutId`, `policyId`, or `sweepId`. The flat alias routes introduce two further identifiers, `agreementId` and `eventId`, whose lookup failures surface as `ERR_AGREEMENT_NOT_FOUND` and `ERR_EVENT_NOT_FOUND` (both HTTP 404) respectively. The first identifier in the path that fails to resolve rejects the request immediately with the matching 404 — `ERR_PROGRAM_NOT_FOUND`, `ERR_FLEET_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_DAMAGE_REPORT_NOT_FOUND`, `ERR_FEE_NOT_FOUND`, `ERR_LOANER_CHECKOUT_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, or `ERR_SWEEP_NOT_FOUND` — before later segments are even examined. Alongside the nested routes, flat cross-program collection routes exist for district-level reporting, and they accept foreign-key filters such as `program_id`, `fleet_id`, `student_account_id`, `asset_unit_id`, `assignment_id`, or `loaner_asset_unit_id` so that a district operator can reach any record from either direction.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix, rendered in the canonical 8-4-4-4-12 dashed hexadecimal form (for example `3f6b0e2a-1c4d-4e5f-8a9b-0c1d2e3f4a5b`). The `created_at` timestamp records creation time, and `updated_at` records the last modification; both are ISO 8601 UTC timestamps with three fractional digits. The `version` is an integer starting at 1 that increments exactly once per request per mutated entity — including system-driven recomputations such as a student's financial posture being re-derived after a fee changes — so a single call that mutates several entities bumps each of their versions by one. An asset's `depreciated_value_cents` and `months_in_service` are recomputed at read time from the logical clock (§3.1) and are not stored mutations: a clock advance that changes those derived figures does not by itself increment the unit's `version`, though the scheduled status transitions it fires (§2.8) do bump the flipped assignments and loaner checkouts. Two record types are deliberately leaner: a FamilyAgreement and an AssetLifecycleEvent carry only `id` and `created_at`, and both `updated_at` and `version` are absent from them, since agreements and lifecycle events are write-once records that are never edited in place.

### 2.6. Monetary Precision and Rounding

All monetary amounts in the system are represented as integer numbers of cents — `premium_cents`, `deductible_cents`, `amount_cents`, and their kin — with zero decimal places. Wherever a calculation produces a fractional cent, the result is rounded half up to a whole cent before it is stored or returned. This applies to the provisional and final damage fees, the late-return fee, the waived portion of a fee, and the straight-line depreciation of an asset.

### 2.7. Optimistic Concurrency Control

Three write operations are protected by optimistic concurrency control, and each names its own expected-version field. Creating an assignment — `POST /api/programs/{progId}/students/{studentId}/assignments` — requires `expected_student_version` carrying the client's last observed `version` of the student account; if another writer has advanced the student's version since the client last read it (for example by settling a fee or signing the agreement), the create is rejected with `ERR_STALE_VERSION` (HTTP 412) so the client cannot act on a posture it has not observed. Retiring an asset — `POST /api/programs/{progId}/asset-units/{assetId}/retire` — requires `expected_asset_unit_version` matching the unit's current `version`, with the same `ERR_STALE_VERSION` rejection on mismatch. Creating an audit sweep — `POST /api/programs/{progId}/audit-sweeps` — requires `expected_program_version` matching the program's current `version`, again rejected with `ERR_STALE_VERSION` on mismatch. The expected-version field is non-optional on exactly these three endpoints; endpoints not listed here do not accept a version field at all, and a request body carrying any of the three expected-version fields to an endpoint that does not declare it — or carrying one of the other two fields to an endpoint that does — is rejected as malformed with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.8. The District Logical Clock and Scheduled Scans

The server runs on a deterministic logical clock: it boots with `current_utc` set to 2026-05-01T00:00:00Z and never reads the wall clock. The only way to move time forward is an admin-only test-driving capability that accepts a `to_iso8601` instant, advances `current_utc` to it, and returns the new `current_utc` as the sole field of the response `data` object. The clock is forward-only: a `to_iso8601` earlier than the current `current_utc` is rejected with `ERR_INVALID_REQUEST` (HTTP 400), while one equal to it is accepted as a no-op advance. All timestamps the server emits, including the returned `current_utc`, are normalized to UTC ISO 8601 with exactly three fractional digits. Advancing the clock fires the system's nightly-scan-style transitions wherever their preconditions now hold: an assignment whose `expected_return_date` has passed without a check-in moves from `ACTIVE` to `OVERDUE`, and a loaner checkout that has been open longer than its `max_loaner_days` cap without a return moves from `OPEN` to `OVERDUE`.

### 2.9. The Asset Lifecycle Event Trail

Every significant moment in a unit's life appends an AssetLifecycleEvent, and the trail is the system's audit backbone. The `event_type` is one of `INTAKE`, `DEPLOY`, `RETURN`, `REPAIR_START`, `REPAIR_COMPLETE`, `RE_IMAGE`, `RETIRE`, `DISPOSE`, `DONATE`, `WRITE_OFF`, or `CORRECTION`. Each event records the `asset_unit_id` it belongs to, a free-form `event_payload` carrying type-specific details (for example a repair's cost or an imaging run's image version), and a server-stamped `occurred_at`. A `CORRECTION` event additionally carries `supersedes_event_id` pointing at the earlier event it reverses; for all other event types `supersedes_event_id` is null. The trail is immutable and read-only, and it survives a unit's departure from service — disposed, donated, and written-off assets are retained with their full history rather than deleted, so the district can always answer for its inventory. Event listings — both the per-unit route and the flat route — accept `event_type` and `supersedes_event_id` filters, and the flat route additionally filters by `asset_unit_id`.

### 2.10. Validation Order of Evaluation

When several rules could reject the same request, the server evaluates them in a fixed order so that the rejection a caller sees is deterministic. A malformed request body — a missing required field, a value of the wrong type, or an enum value outside its declared set — is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Beyond request shape, checks fire in this sequence:

First, authentication: the two identity headers must be present and the role recognized (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, existence: path identifiers resolve left to right, surfacing the resource-specific not-found error for the first unresolved id. Third, program posture: the parent DistrictProgram's `status` must permit the operation — assignment creation requires an `ACTIVE` program, re-imaging requires `SUMMER_COLLECTION` — else `ERR_PROGRAM_STATE_FORBIDS` (HTTP 409). Fourth, concurrency: any endpoint declaring an expected-version field must match the parent entity's current `version` (`ERR_STALE_VERSION`). Fifth, the target resource's own state precondition for the requested transition — a report must be `SUBMITTED` before it can be confirmed, and so on — rejected with `ERR_INVALID_STATE` where no more specific error exists. Sixth, the family-agreement gate: the agreement's `signature_state` must be `SIGNED` before assignment creation, insurance activation, or damage-report submission, else `ERR_AGREEMENT_NOT_SIGNED`. Seventh, the suspension gate: a student whose `financial_posture` is `SUSPENDED` cannot take on new obligations, so assignment creation and loaner checkout both fail with `ERR_STUDENT_SUSPENDED`. Eighth, cross-entity referential integrity: the unit named on a new assignment must actually be deployable (`ERR_ASSET_NOT_READY`), a unit designated as a loaner must clear the grade bar (`ERR_LOANER_CONDITION_TOO_LOW`), and a loaner checkout's unit must genuinely sit in the loaner pool. Ninth, the loaner floor: an allocation that would drain the pool below the program's configured reserve is refused with `ERR_LOANER_FLOOR_BREACH`. Tenth, the temporal windows: the appeal window (`ERR_APPEAL_WINDOW_CLOSED`), the overdue-duration requirements (`ERR_NOT_OVERDUE_LONG_ENOUGH`), the fee write-off age (`ERR_WRITE_OFF_TOO_EARLY`), and the insurance academic-year match (`ERR_POLICY_YEAR_MISMATCH`). Eleventh, fiscal arithmetic on settlement and waiver (`ERR_UNDERPAID`, `ERR_WAIVER_NOT_ELIGIBLE`, `ERR_WAIVER_FORBIDDEN_FOR_FEE_TYPE`). Twelfth, end-of-life criteria on retirement (`ERR_EOL_CRITERIA_NOT_MET`). Thirteenth, the required completion payloads for depot work (`ERR_REPAIR_COST_REQUIRED`, `ERR_IMAGE_VERSION_REQUIRED`). Finally, batch atomicity: a sweep cannot begin while another sweep for the same program is open (`ERR_SWEEP_IN_PROGRESS`), and any atomic batch operation that fails validation is rejected wholesale with `ERR_BATCH_REJECTED` (HTTP 409) — nothing in the batch is created.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Program Year: Fleets and Unit Intake

A `DistrictAdmin` opens a program year by creating a DistrictProgram with a display `program_name` and a `school_year` label such as "2026-2027"; the year scopes both summer collection and end-of-life refresh, and it is the yardstick insurance policies are matched against. The program may also declare `loaner_pool_threshold_pct`, the fraction of the deployable fleet held in reserve as the loaner floor; when omitted, the reserve defaults to 0.10 — ten percent. New programs start in `DRAFT`. Activation moves the program `DRAFT → ACTIVE` and is refused with `ERR_PROGRAM_HAS_NO_FLEET` until at least one fleet exists under the program, because an asset-less program has nothing to run.

Fleets are the purchasing unit. Creating one captures the `fleet_name` (for example "Chromebook-Grade-9-2026"), an `asset_class` of either `DEVICE` or `TEXTBOOK`, the `unit_replacement_cost_cents` used by the fee schedule and end-of-life accounting, the `salvage_value_cents` that floors depreciation, the `useful_life_months` over which the fleet depreciates, and the `in_service_date` from which depreciation runs. A program's fleets can be listed with an optional `asset_class` filter, and the same catalog is reachable across programs through the flat fleet listing filtered by `program_id`.

Unit intake is performed by a `DistrictAdmin` or a `SiteTechnician`. Each unit is registered with an `asset_tag_barcode` that is unique within the program and a manufacturer `serial_number` that is unique within its fleet — a duplicate of either is rejected with `ERR_INVALID_REQUEST` (HTTP 400); an intake `condition_grade` may be supplied and defaults to `A`. Grades run `A` (best) through `B`, `C`, `D`, and `F` (worst), and a unit is re-graded after every repair. A freshly intaken unit begins life in `READY` status and an `INTAKE` event lands on its lifecycle trail. Units are browsable by `lifecycle_status`, by `condition_grade`, or by `assigned_to_student_id`, and the flat unit listing additionally accepts `fleet_id` and `program_id` for cross-fleet reporting.

Depreciation follows the fleet. A unit's `months_in_service` is the number of whole months between the fleet's `in_service_date` and the server's current clock — elapsed days divided by 30.44, the average month length, rounded down — and it is never less than zero and never exceeds the fleet's `useful_life_months`. The `depreciated_value_cents` is then the replacement cost minus accumulated straight-line depreciation: the depreciable amount is `unit_replacement_cost_cents` minus `salvage_value_cents`, each month in service consumes an equal share of that amount (the monthly share multiplied by the months in service, rounded half up to a whole cent), and the result never falls below `salvage_value_cents`. A fleet whose `useful_life_months` is zero depreciates straight to its `salvage_value_cents`. Both figures are derived values recomputed whenever a unit is read; there is no separately cached field to refresh, and a clock advance that changes them does not increment the unit's `version`. Two forced variants override the formula at end of life, described in §3.9.

### 3.2. Student Enrollment and the Family Agreement

Enrollment is a `Registrar` function. The registrar supplies the `student_external_id` (the student information system identifier, unique within the program — a duplicate is rejected with `ERR_INVALID_REQUEST`, HTTP 400), the student's `full_name`, a `grade_level` from 0 through 12, and optionally the `free_lunch_eligible` flag that drives fee-waiver eligibility (defaulting to false). The account is born `ENROLLED` with `financial_posture` set to `CLEAR` and `family_agreement_status` set to `PENDING`, and a FamilyAgreement row is auto-created alongside it in `PENDING` signature state. The roster can be listed with filters on `financial_posture`, `family_agreement_status`, and `status`; the flat student listing adds `program_id`, and the flat agreement listing filters by `student_account_id` or `signature_state`.

A student's `financial_posture` is never set directly — it is derived from their open fees. The `outstanding_balance_cents` is the sum, across the student's fee rows in `ASSESSED` or `APPEALED` status, of `amount_cents` minus `waived_cents` minus `paid_cents`. A zero balance yields `CLEAR`. A positive balance below 10,000 cents (one hundred dollars) yields `FEES_OUTSTANDING`. A balance of 10,000 cents or more yields `SUSPENDED`. Independently of the total, any single `NON_RETURN` fee sitting in `ASSESSED` forces the posture to `SUSPENDED`, because an unreturned asset is the district's strongest signal of non-compliance. The posture is recomputed on every fee mutation — creation, appeal, appeal grant or denial, settlement, waiver, or write-off.

Before anything can be issued, a guardian must act on the family agreement. Signing submits the `acceptable_use_version` label of the document being signed (for example "AUP-2026.v3") together with the `signed_by_guardian_name`; the agreement moves `PENDING → SIGNED`, the server stamps `signed_at`, and the account's `family_agreement_status` flips to `SIGNED`. Declining moves the agreement `PENDING → DECLINED` and flips the account's flag to `DECLINED`, after which the student cannot receive new assignments until a fresh agreement is signed. Both actions require the student to still be `ENROLLED`; otherwise they are refused with `ERR_STUDENT_NOT_ENROLLED`. The agreement is one-per-student, so reading it returns an array containing zero or one element.

When a student leaves, the registrar withdraws them (`ENROLLED → WITHDRAWN`) or graduates them (`ENROLLED → GRADUATED`). Both transitions require the student to still be `ENROLLED`, else `ERR_INVALID_STATE`, and demand a clean desk: no assignment in `ACTIVE` or `OVERDUE` status may remain, else the request is refused with `ERR_OPEN_ASSIGNMENTS`, and the `financial_posture` must be `CLEAR`, else `ERR_FEES_OUTSTANDING`. Unresolved fees can, however, be written off afterward under the rules in §3.7.

### 3.3. Insurance Coverage

Families may shield themselves from damage fees with an annual insurance policy. A `Family` caller creates a policy by quoting a `premium_cents` (the annual premium, non-refundable once the policy is active), a `deductible_cents` applied per incident, a `coverage_cap_cents` bounding the total payout per school year, and the `academic_year` the policy covers. A new policy is `QUOTED` and confers nothing until activated.

Activation is likewise a family action, and it carries three preconditions: the family agreement must be `SIGNED` (else `ERR_AGREEMENT_NOT_SIGNED`), no other policy for the same student may already be `ACTIVE` (else `ERR_ACTIVE_POLICY_EXISTS`), and the policy's `academic_year` must equal the program's `school_year` (else `ERR_POLICY_YEAR_MISMATCH`). On activation the student's `insurance_enrolled` flag becomes true. Policies listable by `status`, or across students by `student_account_id`.

Three exits close a policy, and each one flips `insurance_enrolled` back to false. Exhaustion is automatic: the moment cumulative payouts under the policy reach the `coverage_cap_cents`, the policy moves `ACTIVE → EXHAUSTED`. Cancellation is a family action that moves `ACTIVE → CANCELLED`, but it is refused with `ERR_PENDING_APPEAL_BLOCKS_CANCEL` while any fee tied to a damage report under that policy sits in `APPEALED` — a family cannot cancel mid-dispute. Expiry moves `ACTIVE → EXPIRED` and happens automatically at school-year rollover; a `DistrictAdmin` may also trigger a batch expiry across the whole program, which reports back the `expired_count` and the list of `expired_policy_ids`.

### 3.4. Checking Out Assets to Students

The core operational act of the program year is the assignment: a `Registrar` checks an asset out to a student by naming the `asset_unit_id` and the `expected_return_date` — the summer collection deadline for that assignment — and carrying the `expected_student_version` required by the concurrency rules in §2.7. Assignment listing supports a `status` filter on the per-student nested route; the flat cross-program listing additionally accepts `student_account_id` and `asset_unit_id`. The units currently held by a student are readable as a student sub-resource, and the assignments referencing a given unit are readable as a unit sub-resource.

Because this operation sits at the intersection of several policies, its checks are worth stating in the order they fire. The program must be `ACTIVE` (`ERR_PROGRAM_STATE_FORBIDS`). The student's version must not have advanced beyond `expected_student_version` (`ERR_STALE_VERSION`). The family agreement must be `SIGNED` (`ERR_AGREEMENT_NOT_SIGNED`). The student's `financial_posture` must not be `SUSPENDED` (`ERR_STUDENT_SUSPENDED`). And the named unit must be deployable — in `READY` status with a `condition_grade` other than `F` — else `ERR_ASSET_NOT_READY`.

A successful checkout creates the assignment in `ACTIVE` status, stamps `checked_out_at` from the server clock, and snapshots the unit's current grade into `checkout_condition_grade` so that any damage delta can be measured at return. The unit itself transitions `READY → DEPLOYED`, its `assigned_to_student_id` is set to the student, and a `DEPLOY` event is appended to its lifecycle trail. The `assigned_to_student_id` is null at every other point in the unit's life — it carries a value only while the unit is `DEPLOYED` (including a loaner unit out on checkout); a unit sitting idle in the pool in `LOANER` status has it null. The operation is a cross-aggregate mutation: the student account's `version` increments by one, and the asset unit's `version` increments by one as well.

### 3.5. Returns, Late Fees, and Declared Losses

Time is the first enforcer here. Whenever the logical clock advances past an assignment's `expected_return_date` while `checked_in_at` is still null, the assignment slides from `ACTIVE` to `OVERDUE`; if the student's posture was `CLEAR` and late-return fees are subsequently generated, the posture is recomputed to `FEES_OUTSTANDING` under the derivation rules of §3.2.

Physical return is a `SiteTechnician` action available from either `ACTIVE` or `OVERDUE`, and it takes the `return_condition_grade` observed at the intake desk. The assignment closes to `RETURNED`, `checked_in_at` is stamped from the server clock, and `late_return_days` is computed as the number of whole calendar days the check-in falls after the `expected_return_date`, never less than zero. A return with zero late days generates no fee. Otherwise a `LATE_RETURN` fee is created on a three-tier daily schedule whose boundaries are inclusive on the lower edge: each of the first through seventh late days costs 100 cents, each of the eighth through thirtieth costs 250 cents, and every day from the thirty-first onward costs 500 cents. For a `free_lunch_eligible` student the resulting total is halved, rounded half up to a whole cent. A return from `OVERDUE` follows the same schedule — the accumulated days simply push further into the higher tiers. Two inspections close out the return: if the `return_condition_grade` is worse than the `checkout_condition_grade`, the system files a damage report automatically with `reported_by_role` set to `SYSTEM`, a `damage_category` of `FUNCTIONAL` when the returned grade is `D` or `F` and `COSMETIC` otherwise, and the returned grade as its `observed_condition_grade`; and the unit's lifecycle moves to `READY` when the grade held or improved, or to `IN_REPAIR` whenever the grade worsened, with a `REPAIR_START` event appended in that case.

When an asset is not coming back, a `Registrar` may declare the assignment lost, moving `OVERDUE → LOST`. The assignment must have been `OVERDUE` for at least 30 days; a premature declaration is refused with `ERR_NOT_OVERDUE_LONG_ENOUGH`. Declaring a loss creates a `NON_RETURN` fee assessed at the full `unit_replacement_cost_cents` of the fleet, and the unit itself is pushed to `END_OF_LIFE`, appending a `RETIRE` event to its trail.

### 3.6. Damage Reports and the Fee Schedule

Damage enters the system through a report filed by a `Family` member or a `SiteTechnician`, carrying a `damage_category` of `COSMETIC`, `FUNCTIONAL`, `LIQUID`, `SCREEN`, `LOSS`, or `THEFT`, plus the `observed_condition_grade` at discovery. The `reported_by_role` field records provenance — `FAMILY`, `SITE_TECH`, or `SYSTEM` for the auto-generated reports of §3.5. A new report is a `DRAFT`, and the system immediately computes its `provisional_fee_cents` as a quote of the family's gross exposure: the fleet's `unit_replacement_cost_cents` is multiplied by a severity multiplier keyed to the `damage_category` — 0.10 for `COSMETIC`, 0.45 for `FUNCTIONAL`, 0.80 for `LIQUID`, 0.55 for `SCREEN`, and the full 1.00 for `LOSS` or `THEFT` — and the result is then discounted for the unit's pre-damage `condition_grade`, reduced by 0% for grade `A`, 10% for `B`, 25% for `C`, 50% for `D`, and 75% for `F`. The provisional amount is rounded half up to whole cents. No insurance and no waiver enter the provisional figure; it is a gross quote. Reports on an assignment can be listed and filtered by `status`, and the flat report listing filters by `assignment_id`.

Two categories of damage send the unit to the depot at filing time: when the `damage_category` is `FUNCTIONAL`, `LIQUID`, or `SCREEN` and the `observed_condition_grade` is `D` or `F`, the unit transitions `DEPLOYED → IN_REPAIR` and a `REPAIR_START` event is appended to its trail.

The family formalizes the report by submitting it — `DRAFT → SUBMITTED` — which requires the family agreement to be `SIGNED` (`ERR_AGREEMENT_NOT_SIGNED` otherwise) and freezes the `provisional_fee_cents` at the submitted figure. A `SiteTechnician` then adjudicates. Dismissal moves `SUBMITTED → DISMISSED`: no fee is created, and if the unit had been sent `IN_REPAIR` on account of this report, the system reverts it to `DEPLOYED` and appends a `CORRECTION` event whose `supersedes_event_id` points at the earlier `REPAIR_START` event — the repair was a false alarm.

Confirmation moves `SUBMITTED → CONFIRMED` and computes the `final_fee_cents` in four steps. First, the gross figure is the frozen provisional fee. Second, insurance: if the student's `insurance_enrolled` is true and the policy is `ACTIVE`, the coverage remaining under the policy's `coverage_cap_cents` (after payouts already made this school year) is compared against the gross minus the policy's `deductible_cents`; when the remaining coverage is at least that amount, the insurer pays the gross minus the deductible and the family owes exactly the deductible, and when it is not, the insurer pays only the remaining coverage and the family owes the gross minus that payout. Without an active policy the family owes the gross. Third, the fee waiver: for a `free_lunch_eligible` student, 80 percent of the family's responsibility is waived — rounded half up to a whole cent — and subtracted. Fourth, the enforcement cap: when the report's `observed_condition_grade` is `C`, `D`, or `F`, the family's responsibility is capped at the unit's current `depreciated_value_cents`, so a family is never charged more than the asset was worth; the lesser of the two figures is charged. The outcome becomes `final_fee_cents`, and a single fee row is created whose `amount_cents` is exactly that final family responsibility — not the gross quote — with `fee_type` `INSURANCE_DEDUCTIBLE` whenever an active policy contributed a payout toward the incident and `DAMAGE` otherwise. The student's `lifetime_damage_count` increments by one, and their `financial_posture` is recomputed. If the payout pushed the policy's cumulative payouts to or beyond its `coverage_cap_cents`, the policy exhausts automatically as described in §3.3.

### 3.7. Adjudicating Fees: Appeals, Waivers, Settlement, and Write-Off

Every obligation the system creates is a FeeAssessment, born in `ASSESSED` status with a `fee_type` of `DAMAGE`, `LATE_RETURN`, `NON_RETURN`, or `INSURANCE_DEDUCTIBLE`. The `amount_cents` is the family's final assessed obligation for the fee: for fees born of a confirmed damage report it is the `final_fee_cents` of §3.6 — already net of the insurance payout, the 80 percent free-lunch reduction, and the depreciation cap, none of which are recorded in `waived_cents` — and for `LATE_RETURN` and `NON_RETURN` fees it is the full scheduled amount (the free-lunch halving of a late fee likewise lands inside `amount_cents`). In all cases `waived_cents` and `paid_cents` start at zero and move only through the adjudication actions below. Fees arising from a damage report carry the report's id in `source_damage_report_id`; `LATE_RETURN` and `NON_RETURN` fees leave it null. The fee ledger is listable with filters on `status`, `fee_type`, `source_damage_report_id`, and — across students — `student_account_id`.

A family disputes a fee by appealing it, moving `ASSESSED → APPEALED`. The appeal window is 30 days from assessment: the appeal is accepted through the 30th whole day after the fee's creation and refused with `ERR_APPEAL_WINDOW_CLOSED` once more than 30 whole days have elapsed. Adjudication belongs to the `DistrictAdmin`. Granting the appeal moves `APPEALED → WAIVED` and sets `waived_cents` to the `amount_cents` minus whatever `paid_cents` has already been collected, wiping the remaining obligation. Denying it returns the fee `APPEALED → ASSESSED`, restoring the original obligation. Either way the student's `financial_posture` is recomputed.

Settlement is the paying path: a `DistrictAdmin` records a `payment_cents` amount, which is added to the fee's `paid_cents`, and the fee moves `ASSESSED → SETTLED` only once the collected `paid_cents` plus the incoming payment plus the `waived_cents` together reach the `amount_cents` — an attempt to settle short of that mark is rejected with `ERR_UNDERPAID` (HTTP 422). Settlement is the only action that changes `paid_cents`, so a fee is always settled in a single covering call; overpayment is accepted.

The district's equity lever is the administrative waiver, also a `DistrictAdmin` action, moving `ASSESSED → WAIVED`. It requires the student to be `free_lunch_eligible` (else `ERR_WAIVER_NOT_ELIGIBLE`, HTTP 422), and it applies only to `DAMAGE` and `LATE_RETURN` fees — a `NON_RETURN` fee can never be waived, and the attempt is rejected with `ERR_WAIVER_FORBIDDEN_FOR_FEE_TYPE` (HTTP 422). A successful waiver sets `waived_cents` to `amount_cents` minus `paid_cents`.

Finally, fees that will never be collected can be cleared from the books: a `DistrictAdmin` writes a fee off, moving `ASSESSED → WRITTEN_OFF`. Two conditions guard this: the student must already be `WITHDRAWN` or `GRADUATED` — an active student's fees cannot be written off, and the attempt meets `ERR_STUDENT_ACTIVE` — and the fee must have sat in `ASSESSED` for at least 180 days, else `ERR_WRITE_OFF_TOO_EARLY`. Every one of these transitions recomputes the student's posture, which is what ultimately reopens or closes the gates of §3.4.

### 3.8. The Repair Depot and the Loaner Pool

Depot work closes the loop that damage reports open. Completing a repair is a `SiteTechnician` action that requires the `repair_cost_cents` to be recorded in the event payload — a missing cost is rejected with `ERR_REPAIR_COST_REQUIRED` — and takes the `post_repair_grade` observed after the work. The unit moves `IN_REPAIR → READY`, its `condition_grade` becomes the post-repair grade, and a `REPAIR_COMPLETE` event is appended; a repair completed with a `post_repair_grade` of `F` counts as a failed repair on the unit's record for the end-of-life criteria of §3.9.

The loaner pool keeps students working while their own assets are in the depot. A `SiteTechnician` designates a pool unit by moving it `READY → LOANER`, which requires a `condition_grade` of `A`, `B`, or `C`; a `D` or `F` unit is too tired to lend and the designation is refused with `ERR_LOANER_CONDITION_TOO_LOW`. A loaner checkout is created with a `checkout_reason` of `REPAIR`, `LOSS_PENDING`, or `NEW_ENROLLMENT`, an optional `loaner_asset_unit_id` naming a specific pool unit (which must currently be in `LOANER` status), and an optional `max_loaner_days` hard cap on the loan that defaults to 14 days. The suspension gate of §2.10 applies here exactly as it does to assignments: a `SUSPENDED` student cannot take a loaner, and the attempt fails with `ERR_STUDENT_SUSPENDED`.

When the request omits `loaner_asset_unit_id`, the system selects a unit by policy. Eligible units are those in `LOANER` status with a `condition_grade` of `A`, `B`, or `C`, drawn from a fleet whose `asset_class` matches the class of the student's unit sitting in repair — or, failing that, of the student's open (`ACTIVE` or `OVERDUE`) assignment; a student with neither is matched against pool units of either asset class. Candidates are ranked by `condition_grade` ascending (`A` before `B` before `C`), then by `months_in_service` ascending so that younger units go out first, and finally by the unit's `created_at` ascending as the last tie-break. An empty pool rejects the checkout with `ERR_LOANER_POOL_EXHAUSTED`. And before any allocation commits, the floor is checked: the number of units remaining in `LOANER` after the checkout must be at least the program's `loaner_pool_threshold_pct` multiplied by the number of deployable units — units in `READY` or `LOANER` status — rounded down to a whole number; an allocation that would breach the floor is rejected with `ERR_LOANER_FLOOR_BREACH`. A successful checkout is born `OPEN`, and the selected unit moves `LOANER → DEPLOYED` with a `DEPLOY` event whose payload marks `loaner` as true.

Returning a loaner is a `SiteTechnician` action available from `OPEN` or `OVERDUE`: the checkout closes to `RETURNED`, `returned_at` is stamped from the server clock, and the unit goes back to `LOANER` in the pool. If the elapsed loan exceeded the `max_loaner_days` cap, a `LATE_RETURN` fee is created on the tiered schedule of §3.5, measured from the day the cap was breached. The clock-driven scan moves a still-open checkout from `OPEN` to `OVERDUE` once it has been out longer than its cap with `returned_at` still null. When a loaner stays out, a `DistrictAdmin` escalates it — `OVERDUE → ESCALATED` — but only after the checkout has been `OVERDUE` for at least 7 days; an earlier attempt meets `ERR_NOT_OVERDUE_LONG_ENOUGH`. Escalation creates a `NON_RETURN` fee for the loaner asset's replacement cost and pushes the unit to `END_OF_LIFE`, appending a `RETIRE` event to its trail. A pool unit that is not currently out can be returned to general service — `LOANER → READY` — provided no `OPEN` checkout still references it, else `ERR_LOANER_STILL_OUT`. Checkouts are listable by `status`, and across students and units by `student_account_id` and `loaner_asset_unit_id`; a unit's checkout history is also readable as a unit sub-resource.

### 3.9. Summer Collection, End-of-Life Refresh, and the Audit Sweep

The program year winds down when a `DistrictAdmin` begins summer collection, moving the program `ACTIVE → SUMMER_COLLECTION`. The move is blocked while any assignment has been `OVERDUE` for more than 30 days without a corresponding `NON_RETURN` fee — a fee counts as corresponding when it belongs to the same student and was created no earlier than the assignment's `expected_return_date` — and such a case must first be resolved, typically by declaring the loss, or the transition is refused with `ERR_OVERDUE_UNRESOLVED`. Beginning collection cascades through the fleet: every assignment still `ACTIVE` whose `expected_return_date` has passed flips to `OVERDUE` (assignments are not otherwise closed by the cascade), and every `DEPLOYED` unit of the program moves to `SUMMER_INTAKE`, appending a `RETURN` event to the unit's trail.

Summer is re-imaging season. A `SiteTechnician` starts imaging on a unit in `SUMMER_INTAKE`, moving it to `RE_IMAGING` and appending a `RE_IMAGE` event — but only for units of a `DEVICE` fleet; imaging a textbook is meaningless and is rejected with `ERR_REIMAGE_TEXTBOOK_NOT_ALLOWED`. Completing the work returns the unit to `READY`, and for a device the completion must supply the `image_version`, else `ERR_IMAGE_VERSION_REQUIRED`; the supplied version is recorded into the `event_payload` of the `RE_IMAGE` event appended when imaging began. Textbooks skip imaging entirely: their completion moves them directly from `SUMMER_INTAKE` to `READY`, while invoking completion on a `DEVICE` unit still in `SUMMER_INTAKE` is rejected with `ERR_INVALID_STATE`. Both re-imaging endpoints require the program to be in `SUMMER_COLLECTION`, else `ERR_PROGRAM_STATE_FORBIDS`. Only when nothing remains in `SUMMER_INTAKE` or `RE_IMAGING` (`ERR_UNPROCESSED_SUMMER_INTAKE`) and every audit sweep for the program is `CLOSED` (`ERR_OPEN_AUDIT_SWEEP`) may the `DistrictAdmin` close the program, moving `SUMMER_COLLECTION → CLOSED`.

End-of-life refresh runs on its own criteria. A `DistrictAdmin` retires a unit — from `DEPLOYED` or from `READY` — carrying the `expected_asset_unit_version` of §2.7. Retirement requires cause: the unit's `months_in_service` must have reached the fleet's `useful_life_months`, or the unit must be grade `F` with two failed repairs on its record; anything else is refused with `ERR_EOL_CRITERIA_NOT_MET`. A retired unit moves to `END_OF_LIFE`, appends a `RETIRE` event, and its `version` increments. From `END_OF_LIFE` there are three exits, each forcing a final depreciation value that overrides the linear formula of §3.1. Disposal and donation both require the unit's `assigned_to_student_id` to be null — a unit still on a student's books cannot leave, and the attempt meets `ERR_STILL_ASSIGNED` — and both force the `depreciated_value_cents` to the fleet's `salvage_value_cents`, appending `DISPOSE` or `DONATE` respectively. Write-off is the audit-driven exit: it requires the unit to currently carry the unaccounted flag planted by a sweep's finish-scan (§ below), whatever state that sweep has since reached, else `ERR_NOT_UNACCOUNTED`, and it forces the `depreciated_value_cents` to zero while appending `WRITE_OFF`. All three terminal states — `DISPOSED`, `DONATED`, `WRITTEN_OFF` — retain the record and its event trail for audit rather than deleting anything.

The audit sweep is how the district reconciles record against reality. A `DistrictAdmin` creates a sweep with a `sweep_label` such as "spring-2026-cycle-2" and the `expected_program_version` required by §2.7; the sweep is born `DRAFT` and the program's `version` increments. Beginning the sweep moves it `DRAFT → IN_PROGRESS` and stamps `started_at`, and it is refused with `ERR_SWEEP_IN_PROGRESS` while any other sweep for the same program is `IN_PROGRESS` or `RECONCILING`. During the scan, staff physically locate units and record each one by its `asset_tag_barcode`; every recorded scan answers with a `recorded` flag and the matched `asset_unit_id`, and a barcode that matches no unit of the program still succeeds, answering `recorded` false with a null `asset_unit_id`. When the floor walk is done, finishing the scan moves the sweep `IN_PROGRESS → RECONCILING` unconditionally — unscanned units are the point of the exercise, not a blocker — and computes the `unaccounted_count`: the number of units that were expected but never scanned, where the expected set is every unit of the program whose `lifecycle_status` is not `DISPOSED`, `DONATED`, or `WRITTEN_OFF`, minus the units for which a scan was recorded during this sweep. Each unaccounted unit is flagged, and the flag is cleared again only when the unit physically resurfaces through a return-style flow — an assignment return, a loaner return, the summer-collection cascade, or the start of re-imaging; depot-internal shuffles such as designate-loaner, return-to-pool, repair completion, and retirement do not clear it. Closing the sweep — `RECONCILING → CLOSED`, stamping `closed_at` — requires every flagged unit to be resolved, meaning the unit has reached `WRITTEN_OFF`, `DISPOSED`, or `DONATED`, or its unaccounted flag has been cleared as just described; open cases block the close with `ERR_UNRESOLVED_UNACCOUNTED`. Sweeps are listable by `status` and, across programs, by `program_id`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including all state transitions — return `200 OK`. The table below is a routing summary only: request payloads, response shapes, side effects, and the business rules that gate each call are defined by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/programs` | Create a new DistrictProgram | DistrictAdmin |
| GET | `/api/programs` | List DistrictPrograms (paginated) | DistrictAdmin, SiteTechnician, Registrar, Family |
| GET | `/api/programs/{progId}` | Get a single DistrictProgram | DistrictAdmin, SiteTechnician, Registrar, Family |
| POST | `/api/programs/{progId}/activate` | Transition DistrictProgram DRAFT → ACTIVE | DistrictAdmin |
| POST | `/api/programs/{progId}/begin-summer-collection` | Transition ACTIVE → SUMMER_COLLECTION; triggers Assignment → OVERDUE cascade | DistrictAdmin |
| POST | `/api/programs/{progId}/close` | Transition SUMMER_COLLECTION → CLOSED | DistrictAdmin |
| POST | `/api/programs/{progId}/fleets` | Create an AssetFleet | DistrictAdmin |
| GET | `/api/programs/{progId}/fleets` | List AssetFleets in a program | DistrictAdmin, SiteTechnician, Registrar |
| GET | `/api/programs/{progId}/fleets/{fleetId}` | Get an AssetFleet | DistrictAdmin, SiteTechnician, Registrar |
| POST | `/api/programs/{progId}/fleets/{fleetId}/asset-units` | Intake a new AssetUnit (barcode + serial) | DistrictAdmin, SiteTechnician |
| GET | `/api/programs/{progId}/fleets/{fleetId}/asset-units` | List AssetUnits in a fleet | DistrictAdmin, SiteTechnician, Registrar |
| GET | `/api/programs/{progId}/asset-units/{assetId}` | Get an AssetUnit (cross-fleet) | DistrictAdmin, SiteTechnician, Registrar |
| POST | `/api/programs/{progId}/asset-units/{assetId}/designate-loaner` | Move AssetUnit READY → LOANER | SiteTechnician |
| POST | `/api/programs/{progId}/asset-units/{assetId}/return-loaner-to-pool` | Move AssetUnit LOANER → READY | SiteTechnician |
| POST | `/api/programs/{progId}/asset-units/{assetId}/complete-repair` | Move AssetUnit IN_REPAIR → READY | SiteTechnician |
| POST | `/api/programs/{progId}/asset-units/{assetId}/begin-reimage` | Move AssetUnit SUMMER_INTAKE → RE_IMAGING (DEVICE only) | SiteTechnician |
| POST | `/api/programs/{progId}/asset-units/{assetId}/complete-reimage` | Move AssetUnit RE_IMAGING → READY (or SUMMER_INTAKE → READY for TEXTBOOK) | SiteTechnician |
| POST | `/api/programs/{progId}/asset-units/{assetId}/retire` | Move AssetUnit DEPLOYED or READY → END_OF_LIFE | DistrictAdmin |
| POST | `/api/programs/{progId}/asset-units/{assetId}/dispose` | Move AssetUnit END_OF_LIFE → DISPOSED | DistrictAdmin |
| POST | `/api/programs/{progId}/asset-units/{assetId}/donate` | Move AssetUnit END_OF_LIFE → DONATED | DistrictAdmin |
| POST | `/api/programs/{progId}/asset-units/{assetId}/write-off` | Move AssetUnit END_OF_LIFE → WRITTEN_OFF (audit-triggered) | DistrictAdmin |
| POST | `/api/programs/{progId}/students` | Enroll a StudentAccount | Registrar |
| GET | `/api/programs/{progId}/students` | List students (filterable) | DistrictAdmin, Registrar, SiteTechnician |
| GET | `/api/programs/{progId}/students/{studentId}` | Get a single StudentAccount | DistrictAdmin, Registrar, SiteTechnician, Family |
| POST | `/api/programs/{progId}/students/{studentId}/withdraw` | Student ENROLLED → WITHDRAWN | Registrar |
| POST | `/api/programs/{progId}/students/{studentId}/graduate` | Student ENROLLED → GRADUATED | Registrar |
| GET | `/api/programs/{progId}/students/{studentId}/family-agreement` | Get the FamilyAgreement for a student (array of 0 or 1) | DistrictAdmin, Registrar, Family |
| POST | `/api/programs/{progId}/students/{studentId}/family-agreement/sign` | FamilyAgreement PENDING → SIGNED | Family |
| POST | `/api/programs/{progId}/students/{studentId}/family-agreement/decline` | FamilyAgreement PENDING → DECLINED | Family |
| POST | `/api/programs/{progId}/students/{studentId}/insurance-policies` | Create an InsurancePolicy (QUOTED) | Family |
| GET | `/api/programs/{progId}/students/{studentId}/insurance-policies` | List InsurancePolicies for a student | DistrictAdmin, Registrar, Family |
| GET | `/api/programs/{progId}/students/{studentId}/insurance-policies/{policyId}` | Get an InsurancePolicy | DistrictAdmin, Registrar, Family |
| POST | `/api/programs/{progId}/students/{studentId}/insurance-policies/{policyId}/activate` | InsurancePolicy QUOTED → ACTIVE | Family |
| POST | `/api/programs/{progId}/students/{studentId}/insurance-policies/{policyId}/cancel` | InsurancePolicy ACTIVE → CANCELLED | Family |
| POST | `/api/programs/{progId}/expire-insurance-policies` | Batch-expire all ACTIVE InsurancePolicies in the program | DistrictAdmin |
| POST | `/api/programs/{progId}/students/{studentId}/assignments` | Create an Assignment (check out an AssetUnit) | Registrar |
| GET | `/api/programs/{progId}/students/{studentId}/assignments` | List Assignments for a student | DistrictAdmin, Registrar, SiteTechnician, Family |
| GET | `/api/programs/{progId}/students/{studentId}/assignments/{assignmentId}` | Get an Assignment | DistrictAdmin, Registrar, SiteTechnician, Family |
| POST | `/api/programs/{progId}/students/{studentId}/assignments/{assignmentId}/return` | Return an Assignment (ACTIVE or OVERDUE → RETURNED) | SiteTechnician |
| POST | `/api/programs/{progId}/students/{studentId}/assignments/{assignmentId}/declare-lost` | Assignment OVERDUE → LOST | Registrar |
| POST | `/api/programs/{progId}/students/{studentId}/assignments/{assignmentId}/damage-reports` | File a DamageReport | Family, SiteTechnician |
| GET | `/api/programs/{progId}/students/{studentId}/assignments/{assignmentId}/damage-reports` | List DamageReports on an assignment | DistrictAdmin, Registrar, SiteTechnician, Family |
| GET | `/api/programs/{progId}/students/{studentId}/assignments/{assignmentId}/damage-reports/{reportId}` | Get a DamageReport | DistrictAdmin, Registrar, SiteTechnician, Family |
| POST | `/api/programs/{progId}/students/{studentId}/assignments/{assignmentId}/damage-reports/{reportId}/submit` | DamageReport DRAFT → SUBMITTED (freezes provisional fee) | Family |
| POST | `/api/programs/{progId}/students/{studentId}/assignments/{assignmentId}/damage-reports/{reportId}/confirm` | DamageReport SUBMITTED → CONFIRMED; computes final fee, creates FeeAssessment | SiteTechnician |
| POST | `/api/programs/{progId}/students/{studentId}/assignments/{assignmentId}/damage-reports/{reportId}/dismiss` | DamageReport SUBMITTED → DISMISSED | SiteTechnician |
| GET | `/api/programs/{progId}/students/{studentId}/fees` | List FeeAssessments for a student | DistrictAdmin, Registrar, Family |
| GET | `/api/programs/{progId}/students/{studentId}/fees/{feeId}` | Get a FeeAssessment | DistrictAdmin, Registrar, Family |
| POST | `/api/programs/{progId}/students/{studentId}/fees/{feeId}/appeal` | FeeAssessment ASSESSED → APPEALED (within 30 days) | Family |
| POST | `/api/programs/{progId}/students/{studentId}/fees/{feeId}/appeal-grant` | FeeAssessment APPEALED → WAIVED | DistrictAdmin |
| POST | `/api/programs/{progId}/students/{studentId}/fees/{feeId}/appeal-deny` | FeeAssessment APPEALED → ASSESSED | DistrictAdmin |
| POST | `/api/programs/{progId}/students/{studentId}/fees/{feeId}/waive` | FeeAssessment ASSESSED → WAIVED (free-lunch eligible, DAMAGE or LATE_RETURN only) | DistrictAdmin |
| POST | `/api/programs/{progId}/students/{studentId}/fees/{feeId}/settle` | FeeAssessment ASSESSED → SETTLED | DistrictAdmin |
| POST | `/api/programs/{progId}/students/{studentId}/fees/{feeId}/write-off` | FeeAssessment ASSESSED → WRITTEN_OFF | DistrictAdmin |
| POST | `/api/programs/{progId}/students/{studentId}/loaner-checkouts` | Checkout a loaner (auto-selects a unit if none named) | SiteTechnician |
| GET | `/api/programs/{progId}/students/{studentId}/loaner-checkouts` | List LoanerCheckouts for a student | DistrictAdmin, SiteTechnician, Family |
| GET | `/api/programs/{progId}/students/{studentId}/loaner-checkouts/{checkoutId}` | Get a LoanerCheckout | DistrictAdmin, SiteTechnician, Family |
| POST | `/api/programs/{progId}/students/{studentId}/loaner-checkouts/{checkoutId}/return` | LoanerCheckout OPEN or OVERDUE → RETURNED | SiteTechnician |
| POST | `/api/programs/{progId}/students/{studentId}/loaner-checkouts/{checkoutId}/escalate` | LoanerCheckout OVERDUE → ESCALATED | DistrictAdmin |
| POST | `/api/programs/{progId}/audit-sweeps` | Create an AuditSweep | DistrictAdmin |
| GET | `/api/programs/{progId}/audit-sweeps` | List AuditSweeps | DistrictAdmin, SiteTechnician |
| GET | `/api/programs/{progId}/audit-sweeps/{sweepId}` | Get an AuditSweep | DistrictAdmin, SiteTechnician |
| POST | `/api/programs/{progId}/audit-sweeps/{sweepId}/begin` | AuditSweep DRAFT → IN_PROGRESS | DistrictAdmin |
| POST | `/api/programs/{progId}/audit-sweeps/{sweepId}/scan` | Record a barcode scan against an in-progress sweep | DistrictAdmin, SiteTechnician |
| POST | `/api/programs/{progId}/audit-sweeps/{sweepId}/finish-scan` | AuditSweep IN_PROGRESS → RECONCILING; computes unaccounted count | DistrictAdmin |
| POST | `/api/programs/{progId}/audit-sweeps/{sweepId}/close` | AuditSweep RECONCILING → CLOSED | DistrictAdmin |
| GET | `/api/programs/{progId}/asset-units/{assetId}/lifecycle-events` | List lifecycle events for an AssetUnit (audit trail) | DistrictAdmin, SiteTechnician, Registrar |
| GET | `/api/programs/{progId}/students/{studentId}/asset-units` | List AssetUnits currently assigned to a student | DistrictAdmin, Registrar, SiteTechnician, Family |
| GET | `/api/programs/{progId}/asset-units/{assetId}/assignments` | List Assignments referencing an AssetUnit | DistrictAdmin, Registrar, SiteTechnician |
| GET | `/api/programs/{progId}/asset-units/{assetId}/loaner-checkouts` | List LoanerCheckouts referencing an AssetUnit | DistrictAdmin, SiteTechnician |
| GET | `/api/students` | Flat list of StudentAccounts across programs | DistrictAdmin, Registrar, SiteTechnician |
| GET | `/api/fleets` | Flat list of AssetFleets across programs | DistrictAdmin, SiteTechnician, Registrar |
| GET | `/api/asset-units` | Flat list of AssetUnits across fleets and programs | DistrictAdmin, SiteTechnician, Registrar |
| GET | `/api/assignments` | Flat list of Assignments across students and assets | DistrictAdmin, Registrar, SiteTechnician |
| GET | `/api/damage-reports` | Flat list of DamageReports | DistrictAdmin, Registrar, SiteTechnician |
| GET | `/api/fees` | Flat list of FeeAssessments | DistrictAdmin, Registrar |
| GET | `/api/loaner-checkouts` | Flat list of LoanerCheckouts | DistrictAdmin, SiteTechnician |
| GET | `/api/insurance-policies` | Flat list of InsurancePolicies | DistrictAdmin, Registrar |
| GET | `/api/family-agreements` | Flat list of FamilyAgreements | DistrictAdmin, Registrar |
| GET | `/api/lifecycle-events` | Flat list of AssetLifecycleEvents | DistrictAdmin, SiteTechnician, Registrar |
| GET | `/api/audit-sweeps` | Flat list of AuditSweeps | DistrictAdmin, SiteTechnician |
| GET | `/api/students/{studentId}` | Flat alias for reading a single StudentAccount | DistrictAdmin, Registrar, SiteTechnician, Family |
| GET | `/api/fleets/{fleetId}` | Flat alias for reading a single AssetFleet | DistrictAdmin, SiteTechnician, Registrar |
| GET | `/api/asset-units/{assetId}` | Flat alias for reading a single AssetUnit | DistrictAdmin, SiteTechnician, Registrar |
| GET | `/api/assignments/{assignmentId}` | Flat alias for reading a single Assignment | DistrictAdmin, Registrar, SiteTechnician, Family |
| GET | `/api/damage-reports/{reportId}` | Flat alias for reading a single DamageReport | DistrictAdmin, Registrar, SiteTechnician, Family |
| GET | `/api/fees/{feeId}` | Flat alias for reading a single FeeAssessment | DistrictAdmin, Registrar, Family |
| GET | `/api/loaner-checkouts/{checkoutId}` | Flat alias for reading a single LoanerCheckout | DistrictAdmin, SiteTechnician, Family |
| GET | `/api/insurance-policies/{policyId}` | Flat alias for reading a single InsurancePolicy | DistrictAdmin, Registrar, Family |
| GET | `/api/family-agreements/{agreementId}` | Flat alias for reading a single FamilyAgreement | DistrictAdmin, Registrar, Family |
| GET | `/api/lifecycle-events/{eventId}` | Flat alias for reading a single AssetLifecycleEvent | DistrictAdmin, SiteTechnician, Registrar |
| GET | `/api/audit-sweeps/{sweepId}` | Flat alias for reading a single AuditSweep | DistrictAdmin, SiteTechnician |
| POST | `/_clock/set_current_utc` | Advance the server's deterministic logical clock | DistrictAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_FLEET_NOT_FOUND` | 404 Not Found |
| `ERR_ASSET_NOT_FOUND` | 404 Not Found |
| `ERR_STUDENT_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_DAMAGE_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_FEE_NOT_FOUND` | 404 Not Found |
| `ERR_LOANER_CHECKOUT_NOT_FOUND` | 404 Not Found |
| `ERR_POLICY_NOT_FOUND` | 404 Not Found |
| `ERR_SWEEP_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INTERNAL` | 500 Internal Server Error |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_REPAIR_COST_REQUIRED` | 400 Bad Request |
| `ERR_IMAGE_VERSION_REQUIRED` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PROGRAM_STATE_FORBIDS` | 409 Conflict |
| `ERR_PROGRAM_HAS_NO_FLEET` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STUDENT_NOT_ENROLLED` | 409 Conflict |
| `ERR_STUDENT_SUSPENDED` | 409 Conflict |
| `ERR_STUDENT_ACTIVE` | 409 Conflict |
| `ERR_AGREEMENT_NOT_SIGNED` | 409 Conflict |
| `ERR_OPEN_ASSIGNMENTS` | 409 Conflict |
| `ERR_FEES_OUTSTANDING` | 409 Conflict |
| `ERR_ASSET_NOT_READY` | 409 Conflict |
| `ERR_LOANER_CONDITION_TOO_LOW` | 409 Conflict |
| `ERR_LOANER_STILL_OUT` | 409 Conflict |
| `ERR_LOANER_POOL_EXHAUSTED` | 409 Conflict |
| `ERR_LOANER_FLOOR_BREACH` | 409 Conflict |
| `ERR_ACTIVE_POLICY_EXISTS` | 409 Conflict |
| `ERR_PENDING_APPEAL_BLOCKS_CANCEL` | 409 Conflict |
| `ERR_STILL_ASSIGNED` | 409 Conflict |
| `ERR_NOT_UNACCOUNTED` | 409 Conflict |
| `ERR_EOL_CRITERIA_NOT_MET` | 409 Conflict |
| `ERR_REIMAGE_TEXTBOOK_NOT_ALLOWED` | 409 Conflict |
| `ERR_OVERDUE_UNRESOLVED` | 409 Conflict |
| `ERR_UNPROCESSED_SUMMER_INTAKE` | 409 Conflict |
| `ERR_OPEN_AUDIT_SWEEP` | 409 Conflict |
| `ERR_SWEEP_IN_PROGRESS` | 409 Conflict |
| `ERR_UNSCANNED_ASSETS_REMAIN` | 409 Conflict |
| `ERR_UNRESOLVED_UNACCOUNTED` | 409 Conflict |
| `ERR_APPEAL_WINDOW_CLOSED` | 409 Conflict |
| `ERR_NOT_OVERDUE_LONG_ENOUGH` | 409 Conflict |
| `ERR_WRITE_OFF_TOO_EARLY` | 409 Conflict |
| `ERR_POLICY_YEAR_MISMATCH` | 409 Conflict |
| `ERR_UNDERPAID` | 422 Unprocessable Entity |
| `ERR_WAIVER_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_WAIVER_FORBIDDEN_FOR_FEE_TYPE` | 422 Unprocessable Entity |
| `ERR_BATCH_REJECTED` | 409 Conflict |
