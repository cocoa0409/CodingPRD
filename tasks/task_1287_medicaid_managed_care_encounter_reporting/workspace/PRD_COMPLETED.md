# Medicaid MCO Encounter Reporting API — Product Requirements Document

## 1. Introduction

State Medicaid agencies require managed care organizations (MCOs) to report complete, accurate, and timely encounter data for every service delivered to enrolled members. Encounter records arrive through two channels — direct intake by the plan's own operations team and delegated submission by downstream trading partners — and every record must survive a battery of companion-guide edits before it can be packaged into a submission batch and transmitted to the state. Lateness, incompleteness, and inaccuracy all carry direct financial exposure: the state audits each submission cycle against completeness and accuracy benchmarks, assesses penalties for failures and late files, and reconciles the capitation it paid against risk-adjusted final amounts once encounter data has settled.

This document specifies an API that operates that entire reporting pipeline. It covers program and threshold configuration, member/provider/submitter roster management, submission cycle windows with a deadline-extension workflow, encounter intake with tiered edit validation and an in-place correction loop, batch staging with optimistic concurrency, sealing, and segregation-of-duties transmission, state acknowledgment with per-encounter outcomes and a denial-driven provider quality cascade, void and replace rework, completeness and accuracy audits with a full penalty lifecycle (assessment, appeal, resolution, payment), risk-score computation, provisional-to-final capitation reconciliation, and the final cycle close. All resources are mounted beneath the `/programs` prefix. The audience is the engineering team building the service; every behavioral rule in this document is normative.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The recognized role spellings are exactly `StateAgency`, `McoEncounterOps`, `McoCompliance`, `McoFinance`, and `DelegatedSubmitter`. A request with a missing or malformed header, or a role outside this declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is not permitted on the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The roles partition responsibility along segregation-of-duties lines:

- A `StateAgency` caller is the state Medicaid regulator: it configures programs, cycles, and rate schedules, acknowledges transmitted batches, opens and determines audits, decides extension requests and penalty appeals, closes cycles, and drives the test clock.
- An `McoEncounterOps` caller is the plan's encounter operations team: it manages the roster (members, providers, submitters), intakes and validates encounters, runs corrections, voids and replaces, builds and seals batches, reconciles batches, and acknowledges provider remediation.
- An `McoCompliance` caller transmits sealed batches to the state, requests deadline extensions, and appeals penalty assessments.
- An `McoFinance` caller issues and reconciles capitation statements, computes risk scores, and pays penalties.
- A `DelegatedSubmitter` caller is a delegated entity submitting encounters on behalf of providers; it shares encounter intake with `McoEncounterOps` and can read resources.

Identity semantics differ by role. When `X-User-Role` is `DelegatedSubmitter`, `X-User-ID` is the `id` of the acting Submitter entity; ownership checks on any resource that references a Submitter compare the resource's submitter foreign-key field to `X-User-ID`. In particular, a `DelegatedSubmitter` may only act with `submitter_id` equal to its own `X-User-ID`, and any deviation is rejected with `ERR_FORBIDDEN_FOR_ROLE`. When `X-User-Role` is `StateAgency`, `McoEncounterOps`, `McoCompliance`, or `McoFinance`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `sealed_by_user_id` or `transmitted_by_user_id` on a SubmissionBatch, where transitions write it) but never compares it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. A `limit` that is not an integer or falls outside [1, 100], or an `offset` that is not an integer or is negative, is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by `id` ascending.

The `meta` object of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. Logical Clock and Temporal Semantics

All deadline, lateness, extension-window, and cycle-close logic in the system reads a single server-side logical clock — never the wall clock. Before any client call, the logical clock reads exactly 2026-08-01T00:00:00Z (a fixed startup default). A `StateAgency`-only test-driving capability sets the clock by supplying a `to_iso8601` instant; the capability's response reports the supplied `to_iso8601` string verbatim as `current_utc`. Every rule in this document that compares "now" against a deadline or window resolves "now" through this clock. Wherever a logical-clock reading is written into a resource field (such as a batch's `transmitted_at`), the stored value echoes the clock's current lexical string verbatim — the exact characters last supplied to the clock capability, or the startup default — rather than a reformatted normalization. The same echo discipline applies to request-supplied timestamp and date fields generally (cycle windows, deadlines, enrollment and service dates, rate-schedule windows): they are stored and echoed back in their original lexical form, while every comparison first parses and normalizes them to UTC.

Two interval conventions recur throughout the system and must not be confused. Submission cycle service-date windows are half-open: a cycle covers service dates from its `window_start_at` up to but not including its `window_end_at`. Capitation rate schedule windows are closed: a schedule covers both its `effective_from` and its `effective_to` dates. Calendar-day fields such as enrollment and service dates are expressed as YYYY-MM-DD dates, while window and deadline fields are ISO 8601 timestamps.

### 2.5. Common Resource Properties

Every primary resource — Program, Member, Provider, Submitter, SubmissionCycle, CapitationRateSchedule, Encounter, SubmissionBatch, Audit, PenaltyAssessment, CapitationStatement, RiskScoreSnapshot, and ProviderScorecard — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): starts at 1 on creation and increments by one on every mutation, including mutations driven by cascades originating on other resources. The single exception is the derived-tally recomputation of a SubmissionCycle (§3.3): it refreshes the cycle's `updated_at` but deliberately leaves `version` untouched, because `version` serves as the extension-request OCC pin of §2.7 and silent tally refreshes must not serialize extension writers.

Two sub-resources deviate from this convention. An EncounterLine and a ValidationFinding carry only `id` and `created_at`; both `updated_at` and `version` are absent from them, since lines and findings are immutable once written.

### 2.6. Monetary and Ratio Precision

All monetary amounts in the system — paid and billed amounts, capitation rates, penalty amounts, statement totals — are integers denominated in cents. No monetary field ever carries a fractional value. Where a computation produces a fractional cent (the audit penalty cap, per-member capitation lines, the withheld final total), the result is rounded half up to a whole cent at the exact step the workflow pins.

Ratio quantities — completeness rates, accuracy rate, provider error rate, and risk scores — are represented with exactly 4 decimal places, rounded half up at the final step of their computation.

### 2.7. Optimistic Concurrency Control

Exactly two write operations in the API are guarded by optimistic concurrency pins, and each requires its version field as a non-optional input.

Staging an encounter into a batch requires the request to carry `expected_batch_version`, holding the batch `version` the client last observed. If the batch's current `version` has advanced beyond that observed value — because any other mutation has touched the batch since — the staging request is rejected with `ERR_STALE_VERSION` (HTTP 412), and neither the encounter nor the batch changes.

Requesting a deadline extension on a cycle requires the request to carry `expected_cycle_version`, holding the cycle `version` the client last observed. A mismatch against the cycle's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), leaving the cycle's extension posture unchanged. The version pin is the only serialization point between two writers amending the same cycle's extension posture, because a fresh request while one is pending legitimately supersedes the pending request.

No endpoint other than these two accepts a version field.

### 2.8. Request Evaluation Pipeline

Every request is evaluated against an ordered pipeline of validation stages. A request that fails an earlier stage is rejected immediately and never reaches a later stage, so when several rules could fire on the same malformed request, the earliest stage's error is the one returned. The stages, in order:

1. **Caller context.** `X-User-ID` and `X-User-Role` are present and well-formed, and the role is one of the declared roles; otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Authorization.** The caller's role is permitted on the endpoint; otherwise `ERR_FORBIDDEN_FOR_ROLE`.
3. **Request well-formedness.** The body parses, all required fields are present, scalar and enum values are valid, amounts are not negative, and a `reduced_amount_cents` supplied outside its permitted range fails here; unknown fields are ignored. Violations return `ERR_INVALID_REQUEST`. On encounter intake, the `DelegatedSubmitter` scope rule — the payload must carry a `submitter_id` equal to the caller's `X-User-ID` — is evaluated here, immediately after body well-formedness and before any referenced-existence check; a deviation is rejected with `ERR_FORBIDDEN_FOR_ROLE`.
4. **Referenced existence.** Every resource identifier in the path and body — program, cycle, member, provider, submitter, encounter, batch, audit, penalty, statement, scorecard — must exist; otherwise `ERR_NOT_FOUND`.
5. **State preconditions.** The target resource's current state must permit the requested transition. The generic rejection is `ERR_INVALID_STATE_TRANSITION`; specialized state rejections in this stage are `ERR_BATCH_SEALED` (staging into a batch that is not a draft), `ERR_CYCLE_CLOSED` (batch creation or transmission against a closed cycle), `ERR_ENCOUNTER_NOT_STAGEABLE` (staging an encounter that is not validated or is already staged), `ERR_ENCOUNTER_NOT_REPLACEABLE` (replacement from outside the replaceable states), `ERR_ENCOUNTER_NOT_VOIDABLE` (voiding from a non-acknowledged state), and `ERR_EXTENSION_NOT_PENDING` (approving or denying when no extension is pending).
6. **Optimistic concurrency.** The two version pins of §2.7 are checked here, after state preconditions and before any business gate; a mismatch returns `ERR_STALE_VERSION`.
7. **Business safety gates.** Program posture (`ERR_PROGRAM_RESTRICTED`), segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), suspended parties (`ERR_PROVIDER_SUSPENDED`, `ERR_SUBMITTER_SUSPENDED`), and the provider quality hold (`ERR_PROVIDER_QUALITY_HOLD`).
8. **Referential business rules.** Cycle attribution (`ERR_NO_CYCLE_FOR_SERVICE_DATE`), batch-cycle alignment (`ERR_CYCLE_MISMATCH`), rate coverage (`ERR_RATE_NOT_FOUND`), statement-before-determination (`ERR_STATEMENT_REQUIRED`), and snapshots-before-reconciliation (`ERR_SNAPSHOTS_REQUIRED`).
9. **Fiscal consistency.** The header-lines paid check (`ERR_HEADER_LINES_PAID_MISMATCH`) and line-level sanity (`ERR_PAID_EXCEEDS_BILLED`).
10. **Temporal rules.** Cycle window overlap (`ERR_CYCLE_OVERLAP`), rate schedule overlap (`ERR_RATE_SCHEDULE_OVERLAP`), extension window (`ERR_EXTENSION_WINDOW_CLOSED`), extension regression (`ERR_EXTENSION_REGRESSION`), and cycle-close completeness (`ERR_CYCLE_NOT_CLOSABLE`).
11. **Uniqueness and structural constraints.** Encounter reference reuse (`ERR_DUPLICATE_ENCOUNTER_REF`), one audit per cycle (`ERR_AUDIT_EXISTS`), one statement per cycle (`ERR_STATEMENT_EXISTS`), non-empty seal (`ERR_EMPTY_BATCH`), complete acknowledgment (`ERR_ACK_INCOMPLETE`), audit sample sanity (`ERR_AUDIT_SAMPLE_INVALID`), and resolved denials before partial-batch reconciliation (`ERR_BATCH_HAS_UNRESOLVED_DENIALS`).

### 2.9. Nested Resource Retrieval

Requests that address a resource nested under another (for example, the lines or findings collection of a specific encounter) are validated left to right along the path. Each `{id}` segment is resolved in order, and the request is rejected with `ERR_NOT_FOUND` at the first identifier that does not correspond to an existing resource, before any later segment or business rule is examined. Every resource in the system is addressed by its `id` path parameter, and every single-resource retrieval and every list collection is readable by all five roles.

### 2.10. Program Posture and the Outstanding Penalty Ledger

Each Program carries a derived financial posture that gates transmissions. The program's `penalties_outstanding_cents` is a live ledger: it is the sum of `amount_cents` over all of the program's penalty assessments whose status is `ASSESSED`, `APPEALED`, or `UPHELD`, plus the sum of `reduced_amount_cents` over assessments in status `REDUCED`; assessments in `WAIVED` or `PAID` status contribute nothing. A freshly created program starts with zero outstanding, and its `posture` is derived at creation under the same inclusive comparison: a zero ledger against a `penalty_threshold_cents` of zero satisfies `0 >= 0`, so such a program is born `RESTRICTED`, while any positive threshold leaves it born `OPEN`.

The program's `posture` is recomputed after every event that moves the ledger — penalty creation, waiver, reduction, or payment. When `penalties_outstanding_cents` reaches or exceeds the program's `penalty_threshold_cents` (the comparison is inclusive at the boundary), the posture flips to `RESTRICTED`; when the ledger falls back below the threshold, the posture returns to `OPEN`. A `RESTRICTED` posture blocks batch transmission with `ERR_PROGRAM_RESTRICTED` until the outstanding balance is worked down.

## 3. Business Logic & Workflows

### 3.1. Program Configuration

A `StateAgency` operator onboards an MCO program by supplying its display `name`, the two-letter `state_code` of the state Medicaid agency, and the `companion_guide_version` (for example CG-2026.1) whose edit catalog validations will run against. The program's financial posture anchor, `penalty_threshold_cents`, is required at creation.

Four audit and quality thresholds, plus the penalty cap, may be overridden at creation and otherwise take system defaults. `completeness_threshold` defaults to 0.98 and is the minimum eligibility-benchmark completeness rate for an audit to pass. `accuracy_threshold` defaults to 0.95 and is the minimum sample accuracy rate. `provider_yellow_threshold` defaults to 0.02 and `provider_red_threshold` defaults to 0.05; they drive the provider scorecard tiers described in §3.4. `penalty_cap_percent` defaults to 0.10 and caps an audit-driven penalty at that fraction of the cycle statement's provisional paid amount. A new program begins with `penalties_outstanding_cents` zero and a `posture` derived immediately per §2.10 — `OPEN` for any positive `penalty_threshold_cents`, and `RESTRICTED` when the threshold itself is zero.

### 3.2. Roster Management: Members, Providers, and Delegated Submitters

An `McoEncounterOps` operator enrolls a member by supplying the `program_id`, the state-issued `medicaid_id` (unique within its program, a collision rejected with `ERR_INVALID_REQUEST`), an `aid_category` of `TANF`, `SSI`, `DUAL`, `EXPANSION`, or `CHIP` (which later drives the capitation rate lookup), and the `enrolled_from` date, which is inclusive. The `enrolled_to` date is optional and inclusive when present; a null `enrolled_to` means open-ended enrollment. A new member starts with `status` `ACTIVE`. Disenrollment moves a member from `ACTIVE` to `DISENROLLED` (a member in any other state is rejected with `ERR_INVALID_STATE_TRANSITION`) by supplying a `disenrolled_date`; the member's `enrolled_to` is set to that date, and from then on the referential edit `E201_MEMBER_NOT_ELIGIBLE` fires during validation for any encounter whose `service_from_date` falls outside the closed enrollment interval from `enrolled_from` through `enrolled_to`. The member roster can be listed with filters on `program_id`, `status`, and `aid_category`.

Providers are registered with a `program_id`, a `npi` that must be exactly ten digits and unique within the program (a format or uniqueness violation is rejected with `ERR_INVALID_REQUEST`), and a `taxonomy_code`. A provider's `contract_status` begins `ACTIVE`, and its computed `quality_tier` begins `GREEN`. Suspension moves `contract_status` from `ACTIVE` to `SUSPENDED` (any other starting state is rejected with `ERR_INVALID_STATE_TRANSITION`); there is no reactivation in this surface. Once suspended, two consequences follow: encounter intake naming that provider fails with `ERR_PROVIDER_SUSPENDED`, and the referential edit `E202_PROVIDER_INACTIVE` fires at validation time for the provider's in-flight encounters. The provider list filters on `program_id`, `contract_status`, and `quality_tier`.

Delegated entities are registered with a `program_id`, a display `name`, and a `trading_partner_id` unique within the program (a collision rejected with `ERR_INVALID_REQUEST`), and begin with `status` `ACTIVE`. Suspending a submitter moves it to `SUSPENDED`, after which encounter intake carrying that `submitter_id` fails with `ERR_SUBMITTER_SUSPENDED`. The submitter list filters on `program_id` and `status`.

Intake scope for delegated callers deserves emphasis: when the caller's role is `DelegatedSubmitter`, the encounter payload is required to carry a `submitter_id`, and it must equal the caller's `X-User-ID`; a mismatch is an authorization failure rejected with `ERR_FORBIDDEN_FOR_ROLE`, evaluated immediately after the body's well-formedness checks and before any roster-existence check (§2.8 stage 3). An `McoEncounterOps` caller may omit `submitter_id` entirely, in which case it stays null and marks direct MCO intake.

### 3.3. Submission Cycles, Rate Schedules, and Deadline Extensions

A `StateAgency` operator opens a submission cycle with a `program_id`, a human `label` such as 2026-08, the half-open service window bounded by `window_start_at` and `window_end_at`, and the `submission_deadline_at`. Cycle windows within one program must never overlap, but adjacency is allowed — one cycle's start may equal a sibling's end — and the window end must be strictly after the window start; violations are rejected with `ERR_CYCLE_OVERLAP`. A new cycle starts with `status` `OPEN`, `extension_status` `NONE`, and `effective_deadline_at` equal to `submission_deadline_at`. Its derived tallies — `intake_encounter_count` (encounters attributed to the cycle whose status is anything other than `SUPERSEDED`), `net_accepted_encounter_count`, and `net_accepted_paid_cents` — begin at zero, and `risk_computed_at` stays null until risk scores are first computed. Later recomputation of these tallies refreshes the cycle's `updated_at` but never increments its `version`, which stays reserved as the extension-request OCC pin of §2.7. Cycles can be listed by `program_id` and `status`.

Capitation rate schedules are created by `StateAgency` with a `program_id`, an `aid_category`, a `pmpm_cents` rate that must be a positive number of cents, and a closed effective window from `effective_from` through `effective_to`, both dates inclusive. Schedules are immutable once created — no update or retirement capability exists. Within the same program and aid category, closed windows must not overlap, and unlike cycles, adjacency counts as overlap: a new schedule whose `effective_from` equals an existing schedule's `effective_to` is rejected with `ERR_RATE_SCHEDULE_OVERLAP`. An inverted window — `effective_to` earlier than `effective_from` — draws the same `ERR_RATE_SCHEDULE_OVERLAP` rejection. Rate schedules list by `program_id` and `aid_category`.

When a cycle cannot make its deadline, an `McoCompliance` officer files an extension request carrying the `requested_new_deadline_at`, a free-text `reason`, and the OCC pin `expected_cycle_version`. The request is admissible only against an `OPEN` cycle — any other cycle status is rejected with `ERR_INVALID_STATE_TRANSITION` ahead of the version pin. Three rules then guard the request, and the version pin is evaluated first among them: if the cycle's `version` has advanced since the client last read it, the request fails with `ERR_STALE_VERSION` before any temporal check runs. The request is then only admissible while the logical clock has not passed the cycle's current `effective_deadline_at` — a request exactly at the deadline is still inside the window, and anything later is rejected with `ERR_EXTENSION_WINDOW_CLOSED` — and the requested deadline must be strictly later than the current effective deadline, never equal to or earlier, or the request is rejected with `ERR_EXTENSION_REGRESSION`. A granted request moves `extension_status` from `NONE` to `PENDING`, records the `requested_new_deadline_at`, and increments the cycle's `version`. Filing a fresh request while one is `PENDING` supersedes the pending request under the same version pin, and from a resolved posture of `DENIED` or `APPROVED` a new request likewise returns the cycle to `PENDING`.

The state then adjudicates. Approval by a `StateAgency` operator requires `extension_status` `PENDING` — anything else draws `ERR_EXTENSION_NOT_PENDING` — and moves it to `APPROVED`, at which point the cycle's `effective_deadline_at` becomes the `requested_new_deadline_at`. Denial under the same pending precondition moves it to `DENIED` and leaves `effective_deadline_at` unchanged. In every other posture the effective deadline simply remains the original `submission_deadline_at`.

### 3.4. Encounter Intake and the Edit–Correction Loop

Encounter intake is shared between `McoEncounterOps` and `DelegatedSubmitter` callers. The payload names the `program_id`, the `member_id` of the enrolled member receiving service, the `provider_id` of the rendering provider, a submitter-assigned `encounter_ref`, the `service_from_date` and `service_to_date`, a CMS `place_of_service` code such as 11, the list of ICD-10 `diagnosis_codes` (whose first three characters later feed risk scoring), the header-level `paid_amount_cents`, and the detail `lines`; a `submitter_id` accompanies delegated submissions per §3.2. Each line carries a 1-based `line_number` unique within its encounter, a five-character alphanumeric `procedure_code`, up to four `modifiers` (defaulting to an empty list), a `units` count of at least one, a `billed_amount_cents` of zero or more, and a line `paid_amount_cents` that may not be negative and may not exceed the line's billed amount.

Intake evaluates the pipeline of §2.8 in order: after body well-formedness and roster existence, the suspended-party gates fire (`ERR_PROVIDER_SUSPENDED`, `ERR_SUBMITTER_SUSPENDED`), then cycle attribution, then the fiscal checks, then reference uniqueness. Attribution assigns the encounter's computed `attributed_cycle_id` to the `OPEN` cycle of the program whose half-open window contains the `service_from_date`; when no such cycle exists, intake is rejected with `ERR_NO_CYCLE_FOR_SERVICE_DATE`. Fiscally, `ERR_HEADER_LINES_PAID_MISMATCH` fires exactly when the header `paid_amount_cents` exceeds the sum of the lines' paid amounts — a header equal to or below the lines' paid sum does not trip the check — and any line violating the paid-to-billed or units constraints is rejected with `ERR_PAID_EXCEEDS_BILLED`. Finally, the `encounter_ref` must be unique within its program and submitter scope among encounters whose status is neither `SUPERSEDED` nor `VOIDED`; a collision returns `ERR_DUPLICATE_ENCOUNTER_REF`. A successful intake lands in `RECEIVED` with `correction_sequence` zero, `validation_run_seq` zero, `batch_id` and `replaces_encounter_id` null, and the attributed cycle's `intake_encounter_count` incremented by one. Encounter collections can be filtered by `program_id`, `member_id`, `provider_id`, `submitter_id`, `attributed_cycle_id`, `batch_id`, `replaces_encounter_id`, and `status`; an encounter's lines are exposed as a nested collection, and every encounter response also embeds its `lines` array inline.

Validation is the edit engine of the pipeline. An `McoEncounterOps` operator runs the companion-guide edits against a `RECEIVED` encounter (any other state is rejected with `ERR_INVALID_STATE_TRANSITION`). Each run increments the encounter's `validation_run_seq` and persists one `ValidationFinding` per fired edit, stamped with the producing `run_seq`, the companion-guide `edit_code`, a `tier` of `SYNTAX`, `REFERENTIAL`, or `BUSINESS`, a `severity` of `FATAL` or `WARN`, the `origin` `MCO_EDIT`, the dotted `field_path` of the offending field, and a human-readable `message`. The syntax tier covers `E101_SERVICE_DATE_ORDER` and `E102_DIAG_FORMAT`; the referential tier covers `E201_MEMBER_NOT_ELIGIBLE` and `E202_PROVIDER_INACTIVE`; the business tier covers `E301_DUPLICATE_SUSPECT` and `E302_UNITS_HIGH`. The syntax and referential edits are `FATAL`; the two business edits are `WARN`. `E101_SERVICE_DATE_ORDER` fires when `service_to_date` precedes `service_from_date`. `E102_DIAG_FORMAT` fires at most once per run, on the first diagnosis code failing the pattern `^[A-Z][0-9][0-9A-Z](\.[0-9A-Z]{1,4})?$`. `E201_MEMBER_NOT_ELIGIBLE` fires when the encounter's `service_from_date` falls outside the member's closed enrollment interval. `E202_PROVIDER_INACTIVE` fires when the rendering provider's `contract_status` is not `ACTIVE`. `E301_DUPLICATE_SUSPECT` fires on every correction-loop re-run — any run after the encounter's first, i.e. whenever the encounter's `validation_run_seq` has advanced past one — and whenever another live encounter of the same program (one neither `SUPERSEDED` nor `VOIDED`, and not the original this encounter replaces) shares the encounter's member, provider, and `service_from_date`. `E302_UNITS_HIGH` fires when any line carries `units` greater than 90. The recorded `field_path` is `service_to_date` for E101, `diagnosis_codes` for E102, `service_from_date` for E201 and E301, `provider_id` for E202, and `lines.units` for E302. A run that produces zero `FATAL` findings moves the encounter `RECEIVED → VALIDATED` (warnings may still be attached); a run with one or more `FATAL` findings moves it `RECEIVED → REJECTED`.

Correction is an in-place loop. On a `REJECTED` encounter, the operator submits corrected values for any subset of `service_from_date`, `service_to_date`, `place_of_service`, `diagnosis_codes`, `paid_amount_cents`, and `lines` — fields not supplied keep their current values; the edits re-run over the corrected record with a fresh `validation_run_seq`, new findings are appended alongside the retained prior-run findings, and the encounter moves `REJECTED → VALIDATED` when the re-run is clean of `FATAL` findings or stays `REJECTED → REJECTED` when it is not. The correction path re-applies the same attribution rule (`ERR_NO_CYCLE_FOR_SERVICE_DATE`) — a corrected `service_from_date` may re-attribute the encounter to a different `OPEN` cycle, updating `attributed_cycle_id` and refreshing both cycles' tallies — the same header-lines paid check, and the same line sanity checks as intake. Every validate or correct run — including correction loops that fail again — counts against the provider's quality measurement below.

That measurement lives on the ProviderScorecard, auto-created in `OPEN` status with tier `GREEN` and both counters at zero the first time a validation run — or the state-denial cascade of §3.6 — touches a given provider within a given attributed cycle. Each validate or correct run adds one to the scorecard's `run_count` and adds that run's `FATAL` finding count to its `fatal_finding_count`. The scorecard's `error_rate` is the fatal count divided by the run count — with a single run protecting against a zero denominator — rounded half up to four decimal places. The `tier` is computed from that rounded four-decimal `error_rate`: `RED` when the rate reaches or exceeds the program's `provider_red_threshold` (0.05 by default), `YELLOW` when it reaches or exceeds `provider_yellow_threshold` (0.02 by default) without reaching the red line, and `GREEN` otherwise; both comparisons are inclusive at the boundary. The provider's computed `quality_tier` always mirrors the tier of that provider's most recently updated scorecard, and stays `GREEN` while the provider has none. Scorecards can be listed by `cycle_id`, `provider_id`, and `tier`, and an encounter's findings can be listed across all runs, filterable by `run_seq` and `severity`.

### 3.5. Batch Staging, Sealing, and Transmission

An `McoEncounterOps` operator builds a submission batch against an `OPEN` cycle by supplying its `cycle_id`; creating against a `CLOSED` cycle fails with `ERR_CYCLE_CLOSED`. A new batch starts in `DRAFT`, and its live `encounter_count` and `total_paid_cents` track whatever is currently staged.

Staging moves one validated encounter into one draft batch. The request names the `encounter_id` and the OCC pin `expected_batch_version`, and its checks run in pipeline order. The batch must be `DRAFT` — staging into a sealed or further-advanced batch is rejected with `ERR_BATCH_SEALED`. The encounter must be `VALIDATED` with a null `batch_id`, otherwise `ERR_ENCOUNTER_NOT_STAGEABLE`. The version pin must match the batch's current `version`, otherwise `ERR_STALE_VERSION` — this is the serialization point that keeps two writers who each read the batch earlier from silently interleaving their adds. The provider quality gate follows: if the scorecard for the encounter's provider and attributed cycle is tier `RED` and that scorecard's status is not `ACKNOWLEDGED`, staging is held with `ERR_PROVIDER_QUALITY_HOLD`. Finally the encounter's `attributed_cycle_id` must equal the batch's `cycle_id`, otherwise `ERR_CYCLE_MISMATCH`. A successful stage moves the encounter `VALIDATED → STAGED`, sets its `batch_id`, recomputes the batch's `encounter_count` and `total_paid_cents`, and increments the batch's `version`.

Sealing freezes the batch for review: from `DRAFT` only (`ERR_INVALID_STATE_TRANSITION` otherwise) and only with at least one staged encounter (`ERR_EMPTY_BATCH` otherwise), the seal snapshots `sealed_encounter_count` and `sealed_total_paid_cents` from the live counters and records the sealer's `X-User-ID` in `sealed_by_user_id`, moving the batch `DRAFT → SEALED`. Unsealing reverses the snapshot — from `SEALED` back to `DRAFT`, clearing `sealed_encounter_count`, `sealed_total_paid_cents`, and `sealed_by_user_id` to null — while the staged encounters remain `STAGED` and the live counters keep tracking. Batch collections filter by `cycle_id` and `status`.

Transmission is the compliance act that hands the file to the state, performed by an `McoCompliance` officer and guarded by three gates in pipeline order after the state check. The batch must be `SEALED` (`ERR_INVALID_STATE_TRANSITION` otherwise) and its cycle still `OPEN` (`ERR_CYCLE_CLOSED` otherwise); the program's `posture` must be `OPEN`, a `RESTRICTED` program drawing `ERR_PROGRAM_RESTRICTED`; and segregation of duties forbids the transmitter from being the sealer — a caller whose `X-User-ID` equals the batch's `sealed_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`. A successful transmit moves the batch `SEALED → TRANSMITTED`, stamps `transmitted_at` with the logical clock's current reading — echoed in the exact lexical form last supplied to the clock capability (§2.4) — and `transmitted_by_user_id` with the caller, and moves every staged encounter `STAGED → SUBMITTED` with it. The batch's `late` flag, false until then, is computed at this instant: it is true exactly when `transmitted_at` falls strictly after the cycle's `effective_deadline_at`, with a transmission exactly at the deadline counting as on time.

A late transmission sets off a three-link cascade. First, the system creates a PenaltyAssessment with `reason` `LATE_SUBMISSION`, status `ASSESSED`, and a null `audit_id`; its amount is a flat 500000 cents plus 100000 cents for each whole day late, where whole days are counted at 86400-second granularity and any partial day is discarded — a file transmitted one second past the deadline is late but owes only the flat amount. Second, that amount is added to the program's `penalties_outstanding_cents`. Third, the posture is recomputed per §2.10, and if the outstanding total now reaches `penalty_threshold_cents` the program flips to `RESTRICTED`, gating all further transmissions for the program.

### 3.6. State Acknowledgment and the Denial Cascade

The `StateAgency` acknowledges a `TRANSMITTED` batch by posting `outcomes` — one entry per `SUBMITTED` encounter of the batch, each naming its `encounter_id`, an `outcome` of `ACCEPTED` or `DENIED`, and, for every denial, an `edit_code`. State acknowledgment codes carry a fixed shape: the letter E, the digit 5, two further digits, and then an underscore (the E5xx family). The outcome set must cover each submitted encounter exactly once, with no missing entries and no extras, and every denial must carry a well-formed code; any gap is rejected with `ERR_ACK_INCOMPLETE`.

Three batch outcomes follow from the mix. When every entry is `ACCEPTED`, the batch moves `TRANSMITTED → ACKNOWLEDGED` and each encounter moves `SUBMITTED → ACKNOWLEDGED`, incrementing the cycle's `net_accepted_encounter_count` by one and its `net_accepted_paid_cents` by that encounter's `paid_amount_cents` per accepted leg. A mixed set moves the batch `TRANSMITTED → PARTIAL`: accepted legs fire the same ledger increments, while each denied leg fires the denial cascade below. When every entry is `DENIED`, the batch moves `TRANSMITTED → REJECTED_BATCH` and then, within the same request, immediately back to `DRAFT`: the per-encounter denial side effects do not fire on a whole-file rejection; instead every staged encounter returns to `VALIDATED` with its `batch_id` cleared for rework, the seal snapshots and `sealed_by_user_id` are cleared — while the `transmitted_at` and `transmitted_by_user_id` stamps and the computed `late` flag from the rejected transmission are retained — and the batch's `version` increments.

The denial cascade for an individually denied encounter runs four links. The encounter moves `SUBMITTED → DENIED`, and a ValidationFinding is written on it with `tier` `BUSINESS`, `severity` `FATAL`, `origin` `STATE_ACK`, `run_seq` zero, `field_path` `encounter`, and the state-supplied `edit_code`. The provider's scorecard for the attributed cycle absorbs one into its `fatal_finding_count` without any change to `run_count` — state denials are not validation runs. The `error_rate` is then recomputed, and if it now reaches the program's `provider_red_threshold` the scorecard tier flips to `RED`. Finally, the provider's `quality_tier` mirrors the new tier, and every subsequent attempt to stage this provider's encounters for this cycle is held with `ERR_PROVIDER_QUALITY_HOLD`.

The release valve for that hold is remediation acknowledgment: an `McoEncounterOps` operator acknowledges remediation on a scorecard whose status is `OPEN` and whose tier is `RED` — remediation applies only to red holds, and any other combination is rejected with `ERR_INVALID_STATE_TRANSITION`. The scorecard moves `OPEN → ACKNOWLEDGED`, the staging hold for that provider-and-cycle pair lifts, and the tier itself remains `RED` as the historical measurement of the cycle.

### 3.7. Void, Replace, and Batch Reconciliation

Rework after adjudication takes two shapes. Replacement by an `McoEncounterOps` operator is admissible from `DENIED` or `ACKNOWLEDGED` only — any other status draws `ERR_ENCOUNTER_NOT_REPLACEABLE` — and creates a brand-new encounter from a payload of `encounter_ref`, `service_from_date`, `service_to_date`, `place_of_service`, `diagnosis_codes`, `paid_amount_cents`, and `lines`. The original moves to the terminal `SUPERSEDED` state and its `version` increments; the replacement is born in `RECEIVED` with `replaces_encounter_id` pointing at the original, `correction_sequence` one higher than the original's, and the member, provider, and submitter inherited. Because a superseded record drops out of the intake tally while its replacement joins it, the pair nets out inside `intake_encounter_count`. When the original was `ACKNOWLEDGED`, replacement additionally fires the ledger compensation leg: the cycle's `net_accepted_encounter_count` and `net_accepted_paid_cents` each decrement by the original's contribution, and when the replacement eventually reaches `ACKNOWLEDGED` the ledger re-increments by the replacement's contribution. The replacement payload re-runs the full intake gauntlet — attribution (`ERR_NO_CYCLE_FOR_SERVICE_DATE`), the header-lines paid check, line sanity, and reference uniqueness — and because `SUPERSEDED` records do not count against uniqueness, a corrected record may lawfully reuse a superseded reference. Creation of the replacement returns 201 as a new resource.

Voiding is the simpler leg: an `ACKNOWLEDGED` encounter — and only an `ACKNOWLEDGED` one, otherwise `ERR_ENCOUNTER_NOT_VOIDABLE` — moves to the terminal `VOIDED` state, optionally recording a `void_reason`, and the cycle's net-accepted count and paid total each decrement by the voided encounter's contribution. `SUPERSEDED` encounters are inert: they no longer count in any tally, uniqueness scope, or rate numerator. `VOIDED` encounters likewise leave the uniqueness scope, the net-accepted tallies, and rate numerators, but they remain counted in `intake_encounter_count`, which excludes only `SUPERSEDED` records (§3.3).

A batch closes out through reconciliation by `McoEncounterOps`. An `ACKNOWLEDGED` batch moves straight to the terminal `RECONCILED`. A `PARTIAL` batch may only reconcile once every one of its `DENIED` encounters has been resolved — each replaced or voided first — and reconciling with any denial outstanding is rejected with `ERR_BATCH_HAS_UNRESOLVED_DENIALS`.

### 3.8. The Completeness and Accuracy Audit, and the Penalty Lifecycle

The `StateAgency` opens an audit for a cycle by pinning the sample at creation: a `cycle_id`, a `sample_size` of at least one, and a `defect_count` between zero and the sample size inclusive. At most one audit may exist per cycle, and that uniqueness is examined before the sample values — a second audit for the same cycle draws `ERR_AUDIT_EXISTS`, while a bad sample draws `ERR_AUDIT_SAMPLE_INVALID`. A new audit sits in `DRAFT`, and audits list by `cycle_id` and `status`.

Determination by `StateAgency` requires a `DRAFT` audit (`ERR_INVALID_STATE_TRANSITION` otherwise) and requires the cycle's capitation statement to already exist, since the statement's provisional total anchors the penalty cap — its absence is rejected with `ERR_STATEMENT_REQUIRED`. Determination computes two completeness variants from one numerator, the cycle's `net_accepted_encounter_count`. The informational operations view, `completeness_intake_rate`, divides the numerator by the cycle's `intake_encounter_count` — rejected-but-received encounters depress it — and reads zero when intake is zero. The governing state view, `completeness_eligibility_rate`, divides the same numerator by an eligibility-derived expectation: count the member-months (members whose closed enrollment interval overlaps the cycle window by at least one calendar day, the overlap evaluated at day granularity against the window's start and end dates), multiply by the benchmark of one-half encounter per member-month, and round up to a whole number; the rate is zero when that expectation is zero. Both variants are rounded half up to four decimal places, so a cycle with 3 acknowledged encounters, 4 attributed intake encounters, and 4 member-months reads 0.7500 on the intake variant but 1.5000 on the governing variant — three divided by an expectation of two. The `accuracy_rate` is one minus the ratio of `defect_count` to `sample_size`, also rounded half up to four decimal places. The `determination` is `PASS` exactly when the eligibility-benchmark completeness rate reaches or exceeds the program's `completeness_threshold` and the accuracy rate reaches or exceeds its `accuracy_threshold` — both boundaries inclusive, and both evaluated against the rounded four-decimal rates — and `FAIL` otherwise, moving the audit `DRAFT → DETERMINED`, which is terminal.

A `FAIL` determination spawns the penalty cascade. The system creates a PenaltyAssessment in status `ASSESSED` whose `reason` is `COMBINED` when both components failed, `COMPLETENESS` when only completeness failed, and `ACCURACY` when only accuracy failed. The `amount_cents` starts from deficiency points: each component contributes the shortfall of its measured rate below its threshold expressed in percentage points — a completeness rate of 0.93 against a 0.98 threshold contributes 5 points — with a component that met its threshold contributing zero. The point total converts at 50000 cents per point into a raw amount rounded half up to a whole cent, and the cap is the program's `penalty_cap_percent` of the cycle statement's `provisional_paid_cents`, rounded half up to a whole cent; the assessed amount is the smaller of the raw amount and the cap. The cascade then adds that amount to the program's `penalties_outstanding_cents` and recomputes posture per §2.10, and a flip to `RESTRICTED` immediately blocks further batch transmissions with `ERR_PROGRAM_RESTRICTED`.

From `ASSESSED`, the MCO's recourse runs through three stations. Appeal by an `McoCompliance` officer moves the assessment `ASSESSED → APPEALED` and freezes it there — an appealed penalty must be resolved before it can be paid. Resolution by `StateAgency` supplies a `decision` with three branches, each requiring `APPEALED` (`ERR_INVALID_STATE_TRANSITION` otherwise). A `decision` of `UPHELD` moves the assessment to `UPHELD` with no ledger movement. A `decision` of `WAIVED` moves it to the terminal `WAIVED` and subtracts the full `amount_cents` from `penalties_outstanding_cents` as a compensating leg, recomputing posture. A `decision` of `REDUCED` requires a `reduced_amount_cents` that is zero or greater and strictly less than `amount_cents` — an out-of-range value is a request-validity failure rejected with `ERR_INVALID_REQUEST` ahead of any state check — and moves the assessment to `REDUCED` while subtracting the difference between `amount_cents` and `reduced_amount_cents` from the outstanding ledger, again recomputing posture. A `reduced_amount_cents` supplied alongside an `UPHELD` or `WAIVED` decision must still be an integer when present, but its value is otherwise ignored. Payment by `McoFinance` settles the debt: from any of `ASSESSED`, `UPHELD`, or `REDUCED` (an `APPEALED` assessment draws `ERR_INVALID_STATE_TRANSITION`), the assessment moves to the terminal `PAID`, and the ledger decrements by the effective amount — the `reduced_amount_cents` for a reduced assessment, the `amount_cents` otherwise — with posture recomputed. Penalty assessments list by `cycle_id`, `audit_id`, and `status`.

### 3.9. Risk Scoring, Capitation Reconciliation, and Cycle Close

Capitation begins when `McoFinance` issues the provisional statement for a cycle by supplying its `cycle_id`. Two guards apply in pipeline order: rate coverage is verified first — every aid category with at least one enrolled-overlapping member must have a rate schedule whose closed effective window covers the cycle's window start date, or issuance fails with `ERR_RATE_NOT_FOUND` — and then the one-statement-per-cycle constraint, a duplicate drawing `ERR_STATEMENT_EXISTS`. Issuance computes `member_months` as the count of members whose enrollment interval overlaps the cycle's half-open window by at least one day (the overlap evaluated at calendar-day granularity against the window's start and end dates), and prices the `provisional_paid_cents` with risk pinned at 1.0 for every member: each member-month contributes its category's `pmpm_cents` (rounding half up to a whole cent at 1.0 changes nothing), so the provisional total is the plain sum of applicable per-member rates. The statement is created directly into `PROVISIONAL_ISSUED`, with `final_amount_cents` and `adjustment_cents` null and `withhold_applied` false until reconciliation. Statements list by `cycle_id` and `status`.

Risk scoring is an `McoFinance` capability that computes or overwrites the cycle's RiskScoreSnapshots in three pinned passes, which break the apparent raw-versus-average circularity by evaluating strictly in order. Pass one computes each member's `raw_score` as the sum of condition weights over the distinct three-character diagnosis prefixes found on that member's `ACKNOWLEDGED` encounters whose `service_from_date` falls inside the cycle window, where the known prefixes weigh E11 at 0.8, I50 at 1.2, F32 at 0.4, J45 at 0.3, and N18 at 1.0, unknown prefixes contribute zero, and a member with no qualifying encounters scores a raw zero. Pass two averages: the sum of raw scores divided by the count of all enrolled-overlapping members, zero-raw members included in the denominator. Pass three normalizes: each `normalized_score` is the member's raw score divided by that average, rounded half up to four decimal places, and when the average itself is zero every member normalizes to exactly 1.0. The snapshots are born `COMPUTED`, the run stamps the cycle's `risk_computed_at` with a server timestamp (the same clock that writes `created_at`/`updated_at`, not the logical test clock), the capability responds with the cycle's snapshots as an array sorted by `created_at`, and snapshots list by `cycle_id`, `member_id`, and `status`. Re-running the computation before any reconciliation overwrites the existing `COMPUTED` rows in place — same snapshot identifiers, `version` incremented — while re-running after the snapshots have been consumed is rejected with `ERR_INVALID_STATE_TRANSITION`.

Reconciliation by `McoFinance` requires a `PROVISIONAL_ISSUED` statement (`ERR_INVALID_STATE_TRANSITION` otherwise) and requires risk scores to exist — a null `risk_computed_at` is rejected with `ERR_SNAPSHOTS_REQUIRED`. Reconciliation re-derives the enrolled-overlapping population and its rates at reconcile time, so a member whose aid category lacks a covering schedule draws `ERR_RATE_NOT_FOUND` at this point. The final amount follows a pinned rounding order in which per-member rounding happens first: each member-month's line is that member's `pmpm_cents` multiplied by the member's `normalized_score` — zero for members with no scored encounters unless the zero-average rule lifted everyone to 1.0 — rounded half up to a whole cent; the lines are then summed into a subtotal. Summing unrounded products first and rounding once is forbidden, because it produces different cents. When the cycle's audit determination is `FAIL`, a five-percent withhold applies: the subtotal is multiplied by 0.95 and rounded half up to a whole cent to yield `final_amount_cents`, with `withhold_applied` set true; on any other outcome the subtotal itself is the final amount and `withhold_applied` stays false. The same member-months can therefore reconcile to a materially different total than the provisional issue — a provisional 270000 cents can settle to a final 340000 cents once risk scores apply. The `adjustment_cents` is the final amount minus `provisional_paid_cents`, with a negative value signaling a recovery owed by the MCO. Reconciliation moves the statement `PROVISIONAL_ISSUED → RECONCILED` (terminal) and flips every snapshot of the cycle `COMPUTED → APPLIED`.

The cycle's last act is closure by `StateAgency`. The cycle must be `OPEN` — any other status draws `ERR_INVALID_STATE_TRANSITION` — and four further preconditions must all hold, any miss drawing `ERR_CYCLE_NOT_CLOSABLE`: the logical clock has moved strictly past the `effective_deadline_at`; no batch of the cycle sits in `SEALED`, `TRANSMITTED`, `ACKNOWLEDGED`, or `PARTIAL`; an audit for the cycle exists in `DETERMINED`; and a capitation statement for the cycle exists in `RECONCILED`. Closing sweeps the cycle's remaining `DRAFT` batches into the terminal `DISCARDED` state and returns any of their still-`STAGED` encounters to `VALIDATED` with `batch_id` cleared. A `CLOSED` cycle is terminal; batch creation and transmission against it fail with `ERR_CYCLE_CLOSED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created` — this covers programs, members, providers, submitters, cycles, rate schedules, encounter intake, encounter replacement (which births a new encounter), batches, audits, and capitation statements. All other successful operations, including state transitions, retrievals, and the clock capability, return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/programs` | Create an MCO program with penalty/threshold configuration | StateAgency |
| GET | `/programs/{id}` | Get a program (posture, outstanding penalties) | All roles |
| POST | `/_clock/set_current_utc` | Set the test-driving logical clock | StateAgency |
| POST | `/programs/members` | Enroll a member | McoEncounterOps |
| GET | `/programs/members/{id}` | Get a member | All roles |
| GET | `/programs/members` | List members | All roles |
| POST | `/programs/members/{id}/disenroll` | Disenroll a member effective `disenrolled_date` | McoEncounterOps |
| POST | `/programs/providers` | Register a provider | McoEncounterOps |
| GET | `/programs/providers/{id}` | Get a provider | All roles |
| GET | `/programs/providers` | List providers | All roles |
| POST | `/programs/providers/{id}/suspend` | Suspend a provider's contract | McoEncounterOps |
| POST | `/programs/submitters` | Register a delegated entity / trading partner | McoEncounterOps |
| GET | `/programs/submitters/{id}` | Get a submitter | All roles |
| GET | `/programs/submitters` | List submitters | All roles |
| POST | `/programs/submitters/{id}/suspend` | Suspend a delegated submitter | McoEncounterOps |
| POST | `/programs/cycles` | Create a submission cycle (half-open window; adjacency allowed) | StateAgency |
| GET | `/programs/cycles/{id}` | Get a cycle (tallies, deadlines, extension posture) | All roles |
| GET | `/programs/cycles` | List cycles | All roles |
| POST | `/programs/cycles/{id}/close` | Close a cycle after reconciliation (discards draft batches) | StateAgency |
| POST | `/programs/cycles/{id}/compute-risk-scores` | Compute or overwrite risk score snapshots for the cycle | McoFinance |
| POST | `/programs/cycles/{id}/request-extension` | Request a deadline extension (supersedes a pending request; OCC-guarded) | McoCompliance |
| POST | `/programs/cycles/{id}/approve-extension` | Approve the pending extension | StateAgency |
| POST | `/programs/cycles/{id}/deny-extension` | Deny the pending extension | StateAgency |
| POST | `/programs/rate-schedules` | Create a capitation rate schedule (closed window; adjacency is overlap) | StateAgency |
| GET | `/programs/rate-schedules/{id}` | Get a rate schedule | All roles |
| GET | `/programs/rate-schedules` | List rate schedules | All roles |
| POST | `/programs/encounters` | Intake an encounter (direct or delegated); attributes cycle; starts `RECEIVED` | McoEncounterOps, DelegatedSubmitter |
| GET | `/programs/encounters/{id}` | Get an encounter | All roles |
| GET | `/programs/encounters` | List and filter encounters | All roles |
| GET | `/programs/encounters/{id}/lines` | List the lines of an encounter | All roles |
| GET | `/programs/encounters/{id}/findings` | List validation findings of an encounter across all runs | All roles |
| POST | `/programs/encounters/{id}/validate` | Run companion-guide edits; `VALIDATED` or `REJECTED` | McoEncounterOps |
| POST | `/programs/encounters/{id}/correct` | Correct a `REJECTED` encounter in place and re-run edits | McoEncounterOps |
| POST | `/programs/encounters/{id}/replace` | Supersede a `DENIED` or `ACKNOWLEDGED` encounter and create its replacement | McoEncounterOps |
| POST | `/programs/encounters/{id}/void` | Void an `ACKNOWLEDGED` encounter | McoEncounterOps |
| POST | `/programs/batches` | Create a `DRAFT` batch for an `OPEN` cycle | McoEncounterOps |
| GET | `/programs/batches/{id}` | Get a batch | All roles |
| GET | `/programs/batches` | List batches | All roles |
| POST | `/programs/batches/{id}/encounters` | Stage a `VALIDATED` encounter into a `DRAFT` batch (OCC-guarded) | McoEncounterOps |
| POST | `/programs/batches/{id}/seal` | Seal a non-empty `DRAFT` batch (freezes snapshot totals) | McoEncounterOps |
| POST | `/programs/batches/{id}/unseal` | Reopen a `SEALED` batch to `DRAFT` (clears the seal snapshot) | McoEncounterOps |
| POST | `/programs/batches/{id}/transmit` | Transmit a `SEALED` batch to the state (deadline, posture, and segregation-of-duties gates) | McoCompliance |
| POST | `/programs/batches/{id}/acknowledge` | State acknowledgment with per-encounter outcomes | StateAgency |
| POST | `/programs/batches/{id}/reconcile` | Reconcile an `ACKNOWLEDGED` batch, or a `PARTIAL` batch whose denials are resolved | McoEncounterOps |
| POST | `/programs/audits` | Open a completeness/accuracy audit for a cycle (one per cycle) | StateAgency |
| GET | `/programs/audits/{id}` | Get an audit | All roles |
| GET | `/programs/audits` | List audits | All roles |
| POST | `/programs/audits/{id}/determine` | Compute rates, render the `PASS`/`FAIL` determination, spawn the penalty cascade on `FAIL` | StateAgency |
| GET | `/programs/penalties/{id}` | Get a penalty assessment | All roles |
| GET | `/programs/penalties` | List penalty assessments | All roles |
| POST | `/programs/penalties/{id}/appeal` | Appeal an `ASSESSED` penalty | McoCompliance |
| POST | `/programs/penalties/{id}/resolve` | Resolve an appealed penalty (`UPHELD`, `WAIVED`, or `REDUCED`) | StateAgency |
| POST | `/programs/penalties/{id}/pay` | Pay an `ASSESSED`, `UPHELD`, or `REDUCED` penalty | McoFinance |
| POST | `/programs/capitation-statements` | Issue the provisional statement for a cycle (one per cycle) | McoFinance |
| GET | `/programs/capitation-statements/{id}` | Get a statement | All roles |
| GET | `/programs/capitation-statements` | List statements | All roles |
| POST | `/programs/capitation-statements/{id}/reconcile` | Compute the final amount from risk snapshots and post the reconciliation adjustment | McoFinance |
| GET | `/programs/risk-snapshots/{id}` | Get a risk score snapshot | All roles |
| GET | `/programs/risk-snapshots` | List risk score snapshots | All roles |
| GET | `/programs/scorecards/{id}` | Get a provider scorecard | All roles |
| GET | `/programs/scorecards` | List provider scorecards | All roles |
| POST | `/programs/scorecards/{id}/acknowledge-remediation` | Acknowledge remediation for a `RED` scorecard; lifts the staging hold | McoEncounterOps |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PROGRAM_RESTRICTED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_PROVIDER_SUSPENDED` | 409 Conflict |
| `ERR_SUBMITTER_SUSPENDED` | 409 Conflict |
| `ERR_PROVIDER_QUALITY_HOLD` | 409 Conflict |
| `ERR_NO_CYCLE_FOR_SERVICE_DATE` | 422 Unprocessable Entity |
| `ERR_CYCLE_MISMATCH` | 409 Conflict |
| `ERR_RATE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_STATEMENT_REQUIRED` | 409 Conflict |
| `ERR_SNAPSHOTS_REQUIRED` | 409 Conflict |
| `ERR_HEADER_LINES_PAID_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PAID_EXCEEDS_BILLED` | 422 Unprocessable Entity |
| `ERR_CYCLE_OVERLAP` | 409 Conflict |
| `ERR_RATE_SCHEDULE_OVERLAP` | 409 Conflict |
| `ERR_EXTENSION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_EXTENSION_REGRESSION` | 422 Unprocessable Entity |
| `ERR_CYCLE_NOT_CLOSABLE` | 409 Conflict |
| `ERR_CYCLE_CLOSED` | 409 Conflict |
| `ERR_DUPLICATE_ENCOUNTER_REF` | 409 Conflict |
| `ERR_AUDIT_EXISTS` | 409 Conflict |
| `ERR_STATEMENT_EXISTS` | 409 Conflict |
| `ERR_EMPTY_BATCH` | 409 Conflict |
| `ERR_ACK_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_AUDIT_SAMPLE_INVALID` | 422 Unprocessable Entity |
| `ERR_BATCH_HAS_UNRESOLVED_DENIALS` | 409 Conflict |
| `ERR_ENCOUNTER_NOT_STAGEABLE` | 409 Conflict |
| `ERR_ENCOUNTER_NOT_REPLACEABLE` | 409 Conflict |
| `ERR_ENCOUNTER_NOT_VOIDABLE` | 409 Conflict |
| `ERR_EXTENSION_NOT_PENDING` | 409 Conflict |
| `ERR_BATCH_SEALED` | 409 Conflict |
