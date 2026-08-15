# Mass Tort Claims API — Product Requirements Document

## 1. Introduction

Mass tort settlement programs are among the most operationally demanding fiduciary undertakings in civil litigation. When a global settlement is reached — a defective medical device, an environmental contaminant, a dangerous pharmaceutical — a court-appointed claims administrator inherits a pipeline that can span years: tens of thousands of claimants must be registered and screened against program-specific eligibility criteria, their medical records retrieved and reviewed, their injuries mapped onto a published compensation matrix, and their government and private healthcare liens identified, negotiated, and satisfied before a single dollar leaves the Qualified Settlement Fund. Every step is auditable, every dollar is accounted for twice, and every deviation from protocol invites a fairness challenge from either the plaintiffs' steering committee or the settling defendant.

This document specifies a REST API that operationalizes that pipeline. The system manages a settlement program from its inception — funded with QSF principal and carrying its own logical clock — through claimant registration, eligibility screening, medical record collection and injury verification, tier assignment against a published compensation matrix, lien lifecycle management with time-bound holder response windows, settlement allocation and segregated disbursement, appeal adjudication with automatic re-tiering, and final closure with a sealed, immutable closing statement. Six roles with segregated duties share the workload, optimistic concurrency control protects tier and lien writes against stale reads, and fund conservation invariants guarantee that every cent disbursed traces back to QSF principal. All resources are mounted under the `/settlement-programs` path.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying the role under which that user acts. A request in which either header is missing or malformed — including an `X-User-Role` value outside the six recognized roles — is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is recognized but not permitted to invoke the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The platform recognizes exactly six roles: `ProgramAdministrator`, `IntakeSpecialist`, `RecordsAnalyst`, `LienAnalyst`, `DisbursementApprover`, and `ClaimantRole`.

- `ProgramAdministrator` owns program configuration, tier matrix publication, tier assignment, appeal adjudication, and claim closure. Its `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `IntakeSpecialist` registers claimants, files claims, screens eligibility, and denies claims at intake. Its `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `RecordsAnalyst` uploads and reviews medical records and verifies injuries. Its `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `LienAnalyst` identifies, notifies, negotiates, resolves, and waives liens, and finalizes lien resolution. Its `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `DisbursementApprover` prepares, approves, releases, and voids disbursements, subject to a segregation-of-duties rule against the prepare-disbursement caller. Its `X-User-ID` is an opaque operator identifier; the segregation check described in §2.10 compares it against the recorded prepare caller but never against any entity's `id`.
- `ClaimantRole` represents a claimant and can withdraw the claimant's own claim, file or withdraw an appeal, and dispute a lien in negotiation. When `X-User-Role` is `ClaimantRole`, `X-User-ID` is the `id` of the acting `Claimant`. Ownership is enforced by comparing `X-User-ID` to the relevant `claimant_id`, and a failed ownership check is rejected with `ERR_NOT_FOUND` (HTTP 404). The check applies to: the nested and flat single-resource reads of a claimant or claim; the claimant-scoped writes (withdraw claim, file appeal, withdraw appeal, dispute lien), where it runs after path resolution and before any state validation; and the flat single-resource reads of liens, appeals, disbursements, and closing statements, where the resource's owning claim supplies the `claimant_id`. Nested collection or sub-resource reads under a claim (lien, appeal, disbursement, or closing-statement reads through the nested path) do not re-check ownership beyond the role gate.

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

All list endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, must be at least 1, and may not exceed 100. The `offset` parameter defaults to 0 and may not be negative. These parameters are sanitized rather than rejected: a non-integer value falls back to its default, and an out-of-range value is clamped into the permitted range (`limit` into [1, 100], `offset` to at least 0). List responses are always sorted by `created_at` ascending. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object, where `total_count` reports the total number of matching resources and `has_more` indicates whether additional pages exist beyond the current window.

### 2.4. Common Resource Properties

Every resource in the system carries a server-minted `id` formatted as a bare UUID with no type prefix. Resources created with common metadata also carry `created_at`, an ISO 8601 UTC timestamp with three fractional digits recorded at creation; `updated_at`, a timestamp of the same format refreshed on every mutation; and `version`, an integer that starts at 1 and increments by exactly 1 on every mutation of that resource. `SettlementProgram`, `Claimant`, `Claim`, `TierMatrix`, `MedicalRecord`, `Lien`, `Appeal`, and `Disbursement` all carry the full common set. `ClosingStatement` is an append-only artifact and is the single exception: it carries `id` and `created_at` only, and both `updated_at` and `version` are absent from it entirely.

A `Claim`'s `version` advances not only on direct claim transitions but also on events that conceptually mutate the claim's posture: filing an appeal, upholding, denying, or withdrawing an appeal, resolving a lien, waiving a lien, finalizing liens, and preparing disbursement each increment the claim's `version` by 1, in addition to the tier-assignment transition itself. The cascading claim mutations — the first medical-record upload moving the claim out of `ELIGIBILITY_PASSED`, and the first lien identification moving it out of `TIER_ASSIGNED` — likewise each increment the claim's `version` by 1, as do screening, denial, withdrawal, and closure. Clients that cache claim state must treat any such event as invalidating their copy.

### 2.5. The Program Logical Clock

Each `SettlementProgram` carries its own logical clock in the field `current_utc`. At program creation the clock is initialized to exactly `2026-08-01T00:00:00Z`, and before any explicit advance call it must read exactly that value — the system must never fall back to real wall-clock time. A `ProgramAdministrator` may advance the clock by supplying a `to_iso8601` timestamp, which must be strictly later than the current value; the program's `current_utc` is then set to the supplied instant. A `to_iso8601` that is missing, not a string, or not strictly later than the current value is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A successful advance mutates the program resource, so the program's `updated_at` and `version` advance as with any mutation, and the response body is the updated program object. Lien-holder response deadlines, disbursement release timestamps, and closing-statement seals all read from this program clock, never from wall time. Unlike the wall-clock metadata timestamps of §2.4, these clock-derived stamps keep the program clock's own textual precision: fractional seconds appear in them only when the clock reading itself carries a sub-second part. From the initial clock, for example, a lien notified at program creation carries `holder_response_due_at` of exactly `2026-08-31T00:00:00Z`.

### 2.6. Optimistic Concurrency Control

Two write operations accept a client-supplied claim version and enforce optimistic concurrency against the claim's current state: tier assignment and lien resolution.

A tier-assignment request must carry `expected_claim_version`, a non-optional input holding the value of the claim's `version` the client last observed. If the claim's current `version` does not match — for example because another writer has filed an appeal against the claim, which mutates the claim and advances its version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Likewise, a lien-resolution request must carry `expected_claim_version` matching the owning claim's current `version`; a mismatch — for example because an appeal was filed or liens were finalized since the client last read the claim — is rejected with `ERR_STALE_VERSION` (HTTP 412). The version check on both endpoints is performed before any business-state validation on the same request, so a stale request is reported as stale even if the claim has also moved out of the required state. No endpoint other than these two accepts a version field.

### 2.7. Nested Path Resolution and Flat Aliases

Most resources live in a nested hierarchy: programs contain claimants, claims, and tier matrices; claims contain medical records, liens, appeals, disbursements, and closing statements. Path parameters — `pid`, `cid`, `tmid`, `clid`, `rid`, `lid`, `aid`, and `did` — are validated left to right: every identifier in the path must exist, and each child must actually be nested under its named parent. Any failure of existence or nesting is rejected with `ERR_NOT_FOUND` (HTTP 404).

For every entity type, the API also exposes flat read aliases under the program mount — a single-resource read shaped as the collection segment followed by the bare resource `id` (for example, a flat claimant read or a flat closing-statement read) — plus flat list aliases that accept foreign-key filters such as `settlement_program_id`, `claimant_id`, `claim_id`, `duplicate_of_claimant_id`, `active_appeal_id`, `appealed_tier_matrix_id`, and `requested_tier_matrix_id` for reverse reachability. Both the nested and flat shapes must be supported; they return the same resources.

### 2.8. Monetary Precision and Rounding

All monetary amounts are represented as integer cents in fields ending in `_cents`. Every monetary multiplication rounds half up to integer cents. The attorney fee calculation in particular prescribes a strict rounding order — each lien's fee share is rounded to integer cents first, then summed — and implementations must follow that order exactly, since summing unrounded shares and rounding once can yield a result differing by up to one cent per resolved lien.

### 2.9. Validation Check Order

Every request passes through a fixed gauntlet of checks, evaluated in order. Authentication comes first: header presence and shape (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role authorization (`ERR_INSUFFICIENT_PERMISSIONS`). Next, path resources are resolved (`ERR_NOT_FOUND`). Then, on the two versioned writes, the optimistic-concurrency check (`ERR_STALE_VERSION`) runs before any state validation. Only then does the endpoint's business logic run: the required from-state check (`ERR_CLAIM_INVALID_STATE`, `ERR_LIEN_INVALID_STATE`, `ERR_APPEAL_INVALID_STATE`, or `ERR_DISBURSEMENT_INVALID_STATE`), followed by segregation of duties on disbursement approval (`ERR_SELF_APPROVAL_FORBIDDEN`), matrix referential checks (`ERR_MATRIX_NOT_PUBLISHED`, `ERR_MATRIX_CATEGORY_MISMATCH`), severity range (`ERR_SEVERITY_OUT_OF_RANGE`), eligibility date order (`ERR_ELIGIBILITY_DATE_ORDER`), duplicate active claims (`ERR_DUPLICATE_ACTIVE_CLAIM`), medical-record sufficiency (`ERR_INSUFFICIENT_MEDICAL_RECORDS`, `ERR_NO_QUALIFYING_RECORD`), unresolved liens (`ERR_UNRESOLVED_LIENS_EXIST`), open appeals blocking finalization (`ERR_OPEN_APPEAL_BLOCKS_FINALIZE`), the holder response window (`ERR_HOLDER_WINDOW_OPEN`), negotiated demand caps (`ERR_FINAL_EXCEEDS_ASSERTED`), and finally the fiscal checks on disbursement preparation — fund sufficiency (`ERR_QSF_INSUFFICIENT_FUNDS`) and net-award non-negativity (`ERR_NEGATIVE_NET_AWARD`).

Two orderings deserve emphasis because they decide which error surfaces when several apply. Within lien resolution, the holder-window check for the silent path precedes the negotiated-cap check. Within disbursement preparation, the fund-sufficiency check precedes the net-award non-negativity check.

Body-schema failures — a required field missing or null, or a field failing its type or format check (enum membership, `YYYY-MM-DD` shape, integer range, boolean type) — are rejected with `ERR_INVALID_REQUEST` (HTTP 400). On the two versioned writes, the presence check for `expected_claim_version` itself runs before the version comparison, so a request omitting it is a 400 rather than a 412; elsewhere, field validation runs within the business-logic stage at whatever point the endpoint specifies.

### 2.10. Segregation of Duties and the QSF Ledger

The Qualified Settlement Fund is the program's single source of money. Its principal is fixed at creation in `qsf_principal_cents`; its spendable remainder, `qsf_remaining_cents`, is always the principal minus the sum of `amount_cents` across all disbursements in `RELEASED` state belonging to claims of the program, minus the sum of `qsf_reservation_cents` across all claims of the program currently in `READY_FOR_DISBURSEMENT` status. The remainder is recomputed from this conservation formula on every ledger event (prepare, release, void). Preparing disbursement therefore decrements the remaining balance by the reserved amount, because the claim enters `READY_FOR_DISBURSEMENT` and its reservation begins to count. A `VOIDED` disbursement never counts as a `RELEASED` outflow, and the void refunds the balance through the reservation mechanism: while the claim remains `READY_FOR_DISBURSEMENT` its `qsf_reservation_cents` still counts against the fund, and once every sibling disbursement is `RELEASED` or `VOIDED` the claim leaves `READY_FOR_DISBURSEMENT`, the reservation stops counting, and the unreleased remainder returns to `qsf_remaining_cents` — so voiding the claim's last outstanding disbursement refunds the full un-released balance. Every such recomputation that changes the program mutates it, advancing the program's `updated_at` and `version`.

Disbursement approval is segregated from disbursement preparation: the `X-User-ID` approving a disbursement must differ from the `X-User-ID` that called prepare-disbursement on that claim, and a violation is rejected with `ERR_SELF_APPROVAL_FORBIDDEN` (HTTP 403). This check runs for every disbursement approval on the claim, not just the first.

## 3. Business Logic & Workflows

### 3.1. Program Setup and the Compensation Matrix

Everything begins when a `ProgramAdministrator` creates a settlement program by supplying a unique `program_code` (for example, `MT-GLYPH-2026`), a human-readable `tort_name`, and the fund principal `qsf_principal_cents`; uniqueness of `program_code` is the caller's responsibility and is not enforced server-side. The new program's logical clock reads exactly `2026-08-01T00:00:00Z`, its `matrix_published` flag is `false`, and its spendable remainder equals its principal.

Compensation is parameterized by tier matrix rows. A `ProgramAdministrator` creates each row with an `injury_category` of `QUALIFYING_CAT_A` or `QUALIFYING_CAT_B`, an inclusive severity window bounded by `severity_score_min` and `severity_score_max`, and the `base_award_cents` payable to claims that land in the cell; any other `injury_category` value is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A new row starts in `DRAFT` state and is not assignable. Publishing a row moves it from `DRAFT` to `PUBLISHED` — publishing a row not currently in `DRAFT` is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — and, as a cascade, supersedes any prior `PUBLISHED` row of the same `injury_category` whose severity range overlaps the newly published row — the displaced row's `matrix_state` becomes `SUPERSEDED`. Ranges overlap when the larger of the two minima is less than or equal to the smaller of the two maxima, so windows touching at a single severity value overlap. Once at least one row reaches `PUBLISHED`, the program's `matrix_published` flag reads `true`. Matrix rows can be browsed by `matrix_state`.

### 3.2. Claimant Registration and Eligibility Screening

An `IntakeSpecialist` registers a claimant with `full_name`, `date_of_birth`, `ssn_last4` (exactly four numeric characters), the exposure window `date_of_exposure_start` through `date_of_exposure_end`, the `date_of_diagnosis`, an `injury_category` of `QUALIFYING_CAT_A`, `QUALIFYING_CAT_B`, or `NON_QUALIFYING`, and the `represented_by_counsel` flag that later governs attorney fees. All four date fields are ISO 8601 calendar dates in `YYYY-MM-DD` form; the shape of each date field, the four-digit shape of `ssn_last4`, the enum membership of `injury_category`, and the boolean type of `represented_by_counsel` are each validated at registration, with violations rejected as `ERR_INVALID_REQUEST` (HTTP 400). A claimant record also carries `duplicate_of_claimant_id`, which is null unless the claimant has been marked as a duplicate of another claimant; the claimant list endpoint supports filtering by it for reverse reachability.

Filing a claim for a registered claimant produces a `Claim` whose `status` is `SUBMITTED`, with a server-minted human-readable `claim_number` of the form `CLM-####` — a zero-padded four-digit sequential number (`CLM-0001`, `CLM-0002`, …) drawn from a single counter shared across all programs. The request names the claimant by `claimant_id`; a `claimant_id` that does not identify a claimant of this program is rejected with `ERR_NOT_FOUND` (HTTP 404). Filing performs no duplicate-claim check — that screen happens at eligibility time. All three parallel posture dimensions start at their defaults: `eligibility_status` is `PENDING`, `injury_verification_status` is `PENDING`, and `lien_posture` — which takes one of `NOT_STARTED`, `IDENTIFYING`, `NEGOTIATING`, or `ALL_RESOLVED` over the claim's life — starts at `NOT_STARTED`. The monetary fields `gross_award_cents`, `total_lien_cents`, `attorney_fee_cents`, `net_award_cents`, and `qsf_reservation_cents` all start at 0; `active_appeal_id`, `denied_reason`, and `prepare_disbursement_user_id` all start null. The claim carries `denied_reason` (set at intake denial) and `prepare_disbursement_user_id` (the `X-User-ID` captured at disbursement preparation for the segregation-of-duties check of §2.10) as first-class fields. The claim list endpoint supports filtering by `status`, by owning claimant, and by `active_appeal_id`.

Screening eligibility moves the claim from `SUBMITTED` to `ELIGIBILITY_PASSED` and sets `eligibility_status` to `PASSED`. The screen enforces three business rules, each with its own rejection: the claimant's dates must satisfy the ordering in which `date_of_exposure_start` is on or before `date_of_diagnosis`, which is on or before `date_of_exposure_end`, with violations rejected as `ERR_ELIGIBILITY_DATE_ORDER` (HTTP 422); an `injury_category` of `NON_QUALIFYING` is rejected as `ERR_INELIGIBLE_INJURY` (HTTP 422); and if any other claim exists for the same claimant in a status other than `DENIED`, `WITHDRAWN`, or `CLOSED`, the screen is rejected as `ERR_DUPLICATE_ACTIVE_CLAIM` (HTTP 409). Screening any claim not currently `SUBMITTED` is rejected as `ERR_CLAIM_INVALID_STATE` (HTTP 409).

Denial at intake moves the claim from `SUBMITTED` to the terminal `DENIED` status, sets `eligibility_status` to `FAILED`, and requires a non-empty `denied_reason` — the state check runs first, so denying a claim that is not `SUBMITTED` is `ERR_CLAIM_INVALID_STATE`, and an empty or whitespace-only reason on a `SUBMITTED` claim is rejected as `ERR_INVALID_REQUEST` (HTTP 400). A claimant acting through `ClaimantRole` may instead withdraw the claim, moving it to the terminal `WITHDRAWN` status, but only while the claim is in `SUBMITTED`, `ELIGIBILITY_PASSED`, `RECORDS_PENDING`, or `INJURY_VERIFIED`; a claim that has progressed beyond `INJURY_VERIFIED` is rejected as `ERR_CLAIM_NOT_WITHDRAWABLE` (HTTP 409). Withdrawal enforces the ClaimantRole ownership check of §2.1 before the withdrawability check, so a non-owner is answered `ERR_NOT_FOUND` regardless of claim state.

### 3.3. Medical Records and Injury Verification

Once a claim has passed eligibility, a `RecordsAnalyst` uploads medical records one at a time, each carrying `provider_name`, a `record_type` of `DIAGNOSTIC`, `TREATMENT`, `PHARMACY`, or `HOSPITALIZATION`, a `severity_score` between 0 and 100 assigned by the reviewer, and the reviewer's assertion `confirms_qualifying_injury`. An unrecognized `record_type`, a `severity_score` that is not an integer in [0, 100], or a non-boolean `confirms_qualifying_injury` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The server stamps `received_at` at upload — a wall-clock metadata timestamp of the §2.4 kind, not a reading of the program logical clock — and each new record starts in `PENDING_REVIEW`. The very first upload against a claim in `ELIGIBILITY_PASSED` has a cascading effect: the claim itself advances to `RECORDS_PENDING`. Upload itself carries no claim-status precondition — a record may be uploaded against a claim in any status, and the `ELIGIBILITY_PASSED` cascade is the only status-dependent behavior of an upload; the claim-state gates in this section apply to accept, reject, and verify only.

Record review is a one-way door. Accepting a record moves it from `PENDING_REVIEW` to `ACCEPTED`; rejecting it moves it from `PENDING_REVIEW` to `REJECTED`. Either action while the claim is not in `RECORDS_PENDING` is `ERR_CLAIM_INVALID_STATE`, and either action against a record that has already left `PENDING_REVIEW` is rejected as `ERR_RECORD_ALREADY_REVIEWED` (HTTP 409); when both apply, the claim-state check is evaluated first and surfaces. Records can be listed filtered by `review_state` or `claim_id`.

When the file is ready, the `RecordsAnalyst` verifies the injury, moving the claim from `RECORDS_PENDING` to `INJURY_VERIFIED` and setting `injury_verification_status` to `VERIFIED`. Verification enforces two checks, evaluated in this order: the claim must have at least two medical records in `ACCEPTED` state, otherwise `ERR_INSUFFICIENT_MEDICAL_RECORDS` (HTTP 409); and at least one of those accepted records must carry `confirms_qualifying_injury` equal to true, otherwise `ERR_NO_QUALIFYING_RECORD` (HTTP 422).

### 3.4. Tier Assignment

Tier assignment is the pivot on which the money turns, and it is performed by a `ProgramAdministrator`. The client proposes a `tier_matrix_id` and must also supply `expected_claim_version` per the optimistic-concurrency rule in §2.6. On success the claim moves from `INJURY_VERIFIED` to `TIER_ASSIGNED`.

Five preconditions guard the transition, evaluated after the version check. The claim must currently be `INJURY_VERIFIED` (`ERR_CLAIM_INVALID_STATE`). The program must have at least one tier matrix row in `PUBLISHED` state, otherwise `ERR_NO_PUBLISHED_MATRIX` (HTTP 409). The supplied `tier_matrix_id` must belong to this program and itself be in `PUBLISHED` state, otherwise `ERR_MATRIX_NOT_PUBLISHED` (HTTP 409). The claimant's `injury_category` must equal the matrix row's `injury_category`, otherwise `ERR_MATRIX_CATEGORY_MISMATCH` (HTTP 422). Finally, the claim's severity score — defined as the maximum `severity_score` across the claim's `ACCEPTED` medical records — must fall within the matrix row's severity window, bounded by `severity_score_min` and `severity_score_max` inclusively on both ends, otherwise `ERR_SEVERITY_OUT_OF_RANGE` (HTTP 422).

On success, the tier-assignment calculation sets `gross_award_cents` to the matched matrix row's `base_award_cents`, using only the claim's accepted records and the requested matrix row. The attorney fee calculation then runs (§3.7), `net_award_cents` is recomputed as the gross award minus total liens minus attorney fee with a floor of zero, and the claim's `lien_posture` flips to `IDENTIFYING`.

### 3.5. The Lien Lifecycle

A `LienAnalyst` identifies liens against a claim in `TIER_ASSIGNED` or `LIENS_PENDING` status by supplying a `lien_type` of `MEDICARE`, `MEDICAID`, `PRIVATE_INSURER`, `MEDICAL_PROVIDER`, or `VA_TRICARE`, a `holder_name`, and the `asserted_amount_cents` the holder initially claims; identification against a claim in any other status is rejected as `ERR_CLAIM_INVALID_STATE` (HTTP 409), an unrecognized `lien_type` or a negative or non-integer `asserted_amount_cents` is rejected as `ERR_INVALID_REQUEST` (HTTP 400), and the claim-status check runs before these body validations. Each new lien starts in `IDENTIFIED` with `provisional_demand_cents`, `final_demand_cents`, `holder_response_due_at`, and `resolution_notes` all null, and the first identification against a `TIER_ASSIGNED` claim advances the claim itself to `LIENS_PENDING` — later identifications (made while the claim is `LIENS_PENDING`) leave the claim status alone.

Notifying the holder moves a lien from `IDENTIFIED` to `NOTIFIED` and is only permitted while the claim is in `LIENS_PENDING`; the lien's own from-state check (`ERR_LIEN_INVALID_STATE`) is evaluated before the claim-status precondition (`ERR_CLAIM_INVALID_STATE`), so a stale lien state surfaces first. Notification triggers the provisional-demand calculation: a discount is applied to `asserted_amount_cents` according to holder type, each multiplication rounded half up to integer cents. A `MEDICARE` lien's `provisional_demand_cents` is sixty percent of the asserted amount; `MEDICAID` is fifty percent; `VA_TRICARE` is seventy percent; `PRIVATE_INSURER` is seventy-five percent. A `MEDICAL_PROVIDER` lien receives a hardship-dependent discount: if the claim's `gross_award_cents` is below the hardship floor of five million cents (that is, $50,000), the provisional demand is forty percent of the asserted amount; otherwise it is eighty percent. The provisional figure never exceeds the asserted amount and exists for claimant planning while the holder's response window runs. That window is fixed at thirty days: notification stamps `holder_response_due_at` as the program's `current_utc` plus thirty days, read from the program logical clock.

Resolution has two paths, and both are subject to the optimistic-concurrency rule of §2.6: the request must carry `expected_claim_version` matching the claim's current `version`, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412) before any lien-state logic runs.

The **negotiated path** resolves a lien from `IN_NEGOTIATION`. The analyst supplies `final_demand_cents`, which must be at least zero and no more than `asserted_amount_cents` — an amount that is missing, not an integer, or below zero is rejected as `ERR_INVALID_REQUEST` (HTTP 400), and an amount above the asserted figure is rejected as `ERR_FINAL_EXCEEDS_ASSERTED` (HTTP 422). Opening negotiation is itself a transition: beginning negotiation moves a lien from `NOTIFIED` to `IN_NEGOTIATION`, and the same operation also serves as the return ramp from `DISPUTED` back into `IN_NEGOTIATION`.

The **silent-holder path** resolves a lien directly from `NOTIFIED` when the holder has failed to respond in time: the program's `current_utc` must be strictly later than `holder_response_due_at`, otherwise the attempt is rejected as `ERR_HOLDER_WINDOW_OPEN` (HTTP 422). On this path the server sets `final_demand_cents` equal to the full `asserted_amount_cents` — the discount evaporates with the deadline — and the client cannot override the figure on this path; any `final_demand_cents` supplied by the client on this path is ignored. On either path the client may optionally supply `resolution_notes`, which are written onto the lien when present.

Either resolution path recomputes the claim's `total_lien_cents` as the sum of `final_demand_cents` across the claim's liens in `RESOLVED` state and recomputes `net_award_cents`, and both advance the claim's `version` by 1. Neither resolution path re-runs the attorney fee calculation: `attorney_fee_cents` is left unchanged, and `net_award_cents` is recomputed against the stored fee. A lien may instead be waived from `IDENTIFIED`, `NOTIFIED`, or `IN_NEGOTIATION`; waiving requires non-empty `resolution_notes` (a missing, empty, or whitespace-only note is `ERR_INVALID_REQUEST`), sets `final_demand_cents` to zero, and likewise recomputes the claim totals (`total_lien_cents` and `net_award_cents`, again leaving `attorney_fee_cents` unchanged) and advances the claim's `version` by 1. The `resolution_notes` field holds the analyst's negotiation notes and remains null until the analyst supplies them. The claimant, acting through `ClaimantRole`, may dispute a lien that is `IN_NEGOTIATION`, moving it to `DISPUTED`; a `LienAnalyst` can then begin negotiation again to bring it back. Any of these lien operations attempted against a lien in the wrong `state` is rejected as `ERR_LIEN_INVALID_STATE` (HTTP 409). Liens can be listed filtered by `state`, `lien_type`, or owning claim.

When every lien on the claim has reached `RESOLVED` or `WAIVED`, the `LienAnalyst` finalizes liens, moving the claim from `LIENS_PENDING` to `LIENS_RESOLVED` and setting `lien_posture` to `ALL_RESOLVED`. Finalization requires the claim to currently be `LIENS_PENDING` (`ERR_CLAIM_INVALID_STATE` otherwise); it is blocked, with `ERR_UNRESOLVED_LIENS_EXIST` (HTTP 409), while any lien remains in `IDENTIFIED`, `NOTIFIED`, `IN_NEGOTIATION`, or `DISPUTED`; and it is blocked, with `ERR_OPEN_APPEAL_BLOCKS_FINALIZE` (HTTP 409), while the claim's `active_appeal_id` is non-null. The three checks run in that order: claim state, then unresolved liens, then open appeal. Finalization recomputes `total_lien_cents` from the resolved liens and recomputes `net_award_cents`, and advances the claim's `version` by 1.

### 3.6. Appeals and Re-Tiering

A claimant who disputes the assigned tier may file an appeal while the claim is in `TIER_ASSIGNED`; the ClaimantRole ownership check of §2.1 runs first, so a non-owner is answered `ERR_NOT_FOUND` regardless of claim state. The filing names the `appealed_tier_matrix_id` — the matrix row being disputed, recorded as-is without any state validation — and the `requested_tier_matrix_id` the claimant believes applies, along with free-text `grounds` of at least twenty characters; a `requested_tier_matrix_id` that does not identify a `PUBLISHED` row of this program is rejected as `ERR_MATRIX_NOT_PUBLISHED`, and short or missing grounds fall under `ERR_INVALID_REQUEST`. Filing is rejected with `ERR_CLAIM_INVALID_STATE` when the claim is not `TIER_ASSIGNED`, and with `ERR_APPEAL_ALREADY_OPEN` (HTTP 409) when `active_appeal_id` is already non-null; these run before the body validations, in that order. A successful filing creates the appeal in `FILED` state with `resolution_rationale` null, writes its id into the claim's `active_appeal_id`, and advances the claim's `version` by 1. Appeals can be listed filtered by `state`, `claim_id`, `appealed_tier_matrix_id`, or `requested_tier_matrix_id`.

Adjudication belongs to the `ProgramAdministrator`. Beginning review moves an appeal from `FILED` to `UNDER_REVIEW`; upholding and denying are adjudication outcomes and each is permitted only from `UNDER_REVIEW`, never directly from `FILED`; any appeal action against an appeal in the wrong state is `ERR_APPEAL_INVALID_STATE` (HTTP 409). Both adjudication outcomes require a `resolution_rationale` of at least twenty characters, written onto the appeal at decision time.

Upholding the appeal moves it to `UPHELD` and is the most consequential operation in the system: the requested matrix row must be `PUBLISHED` (`ERR_MATRIX_NOT_PUBLISHED`), and on success the tier-assignment calculation re-runs against the `requested_tier_matrix_id`, updating `gross_award_cents` — uphold re-runs only the arithmetic of §3.4, not its preconditions, so no category-match or severity-range check is repeated and the claim's `status` stays `TIER_ASSIGNED`; the attorney fee calculation re-runs, updating `attorney_fee_cents`; `total_lien_cents` is unchanged; `net_award_cents` is recomputed; and the claim's `active_appeal_id` is cleared to null. Denying the appeal moves it to `DENIED` and clears `active_appeal_id` without touching the award figures. Either outcome advances the claim's `version` by 1. The claimant may also withdraw an appeal, but only while it is still `FILED`; withdrawal moves it to `WITHDRAWN`, clears `active_appeal_id`, and advances the claim's `version`. Because every appeal event advances the claim's `version`, any client holding a pre-appeal `version` will find its next tier assignment or lien resolution rejected as stale — this is the intended serialization point between the appeal cycle and the lien and tier writes.

### 3.7. Award Arithmetic and the Allocation Waterfall

Three figures govern every claim's money, and all three are maintained in integer cents.

The **gross award** is the matched matrix row's `base_award_cents`, as described in §3.4.

The **attorney fee** applies a forty percent contingency rate. When the claimant's `represented_by_counsel` is false, `attorney_fee_cents` is zero. When the claimant is represented, the calculation follows a strict nested-rounding order: for each of the claim's liens in `RESOLVED` state, that lien's pro-rata fee share is computed by multiplying its `final_demand_cents` by the forty percent rate and rounding the product half up to integer cents; those per-lien shares are summed into a lien-share total; the base fee is computed by multiplying the difference between `gross_award_cents` and `total_lien_cents` by the forty percent rate, rounding that product half up to integer cents; and `attorney_fee_cents` is the base fee minus the lien-share total, floored at zero. Rounding each lien line before summing — rather than summing unrounded shares and rounding once — is the canonical order, and the two orders can diverge by up to one cent per resolved lien. The attorney fee calculation runs only at tier assignment (§3.4) and when an appeal is upheld (§3.6); lien resolution, lien waiver, and lien finalization recompute `total_lien_cents` and `net_award_cents` (§3.5) but never re-run it, so `attorney_fee_cents` persists unchanged through the lien lifecycle.

The **net award** is `gross_award_cents` minus `total_lien_cents` minus `attorney_fee_cents`, floored at zero. It is recomputed at tier assignment, at every lien resolution or waiver, at lien finalization, and at every appeal outcome that re-tiers the claim.

When liens are finalized, a `DisbursementApprover` prepares disbursement, moving the claim from `LIENS_RESOLVED` to `READY_FOR_DISBURSEMENT`. Preparation enforces two fiscal checks: the program's `qsf_remaining_cents` must be at least the claim's `net_award_cents`, otherwise `ERR_QSF_INSUFFICIENT_FUNDS` (HTTP 402); and `net_award_cents` itself must be at least zero, otherwise `ERR_NEGATIVE_NET_AWARD` (HTTP 422). On success, `qsf_reservation_cents` is set equal to `net_award_cents` at reservation time, the program's `qsf_remaining_cents` is decremented by that amount, the claim records the caller's `X-User-ID` in `prepare_disbursement_user_id`, and the allocation waterfall spawns the claim's `Disbursement` rows, all in `PENDING` state with `released_at` null — always one for the claimant, plus one for the attorney when the claimant is represented, plus one per lien-holder bucket grouped by payee. The response body is the updated claim object.

The waterfall pays in a fixed order, and the order matters because the final bucket is the residual. First come the lien holders: one disbursement per distinct `holder_name` among the claim's `RESOLVED` liens, holders ordered by the earliest `created_at` among that holder's liens ascending, each with `payee_role` of `LIEN_HOLDER`, the holder's name as `payee_name`, and `amount_cents` equal to the sum of that holder's `final_demand_cents`. Second comes counsel: when `represented_by_counsel` is true, a disbursement with `payee_role` of `ATTORNEY`, `payee_name` of "Counsel of Record", and `amount_cents` equal to `attorney_fee_cents`. Last comes the claimant: a disbursement with `payee_role` of `CLAIMANT`, the claimant's `full_name` as `payee_name`, and `amount_cents` equal to whatever remains after the first two buckets — so the sum of all disbursement amounts for a claim always equals `net_award_cents` exactly. Disbursement amounts are computed by this waterfall and are never edited by hand.

### 3.8. Disbursement Execution, Closure, and Audit

A prepared disbursement travels a short but controlled path. Approval moves it from `PENDING` to `APPROVED` and enforces the segregation-of-duties rule of §2.10: the approver's `X-User-ID` must differ from the `X-User-ID` that prepared disbursement on this claim, else `ERR_SELF_APPROVAL_FORBIDDEN` (HTTP 403). Release moves it from `APPROVED` to `RELEASED` and stamps `released_at` with the program's `current_utc`; releasing also credits the QSF ledger, since `qsf_remaining_cents` counts only `RELEASED` outflows against principal. Acting on a disbursement in any other state is `ERR_DISBURSEMENT_INVALID_STATE` (HTTP 409). Disbursements can be listed filtered by `state` or `claim_id`.

The claim itself crosses from `READY_FOR_DISBURSEMENT` to `DISBURSED` automatically when the last of its sibling disbursements leaves the pending set — that is, when every disbursement on the claim is in `RELEASED` or `VOIDED`. Should a claim-level completion ever be attempted while siblings remain in `PENDING` or `APPROVED`, it is rejected as `ERR_DISBURSEMENTS_PENDING` (HTTP 409).

A disbursement that should never have been created can be voided, but only from `PENDING`: voiding moves it to `VOIDED` and refunds the program's `qsf_remaining_cents` through the reconciliation mechanism of §2.10 — a voided disbursement never counts as a `RELEASED` outflow, and when the void is the event that leaves every sibling `RELEASED` or `VOIDED`, the claim crosses to `DISBURSED`, its reservation stops counting against the fund, and the un-released remainder of the reservation returns to the balance. A disbursement that has already been approved cannot be voided.

Closure is the `ProgramAdministrator`'s final act. Closing a claim requires it to be `DISBURSED` (`ERR_CLAIM_INVALID_STATE` otherwise), moves it to the terminal `CLOSED` status, and seals an immutable `ClosingStatement`: an append-only audit artifact carrying the owning `claim_id`, the claim's `gross_award_cents`, `total_lien_cents`, `attorney_fee_cents`, and `net_award_cents` as a snapshot at closing, a rendered `statement_body`, and a `sealed_at` timestamp taken from the program clock. A closing statement has no `updated_at` and no `version` — once sealed, it never changes. The close operation's response body is the updated claim object; the sealed statement is retrievable through the closing-statement list and read endpoints. Closing statements can be listed per claim and filtered by `claim_id`.

## 4. Endpoint Definitions

New resources are returned with HTTP 201; all modifications, reads, and state transitions return HTTP 200. The flat aliases listed below return the same resources as their nested counterparts and exist for reverse reachability.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | /settlement-programs | Create a settlement program | ProgramAdministrator |
| GET | /settlement-programs | List settlement programs | ProgramAdministrator, IntakeSpecialist, RecordsAnalyst, LienAnalyst, DisbursementApprover, ClaimantRole |
| GET | /settlement-programs/{pid} | Get a settlement program | ProgramAdministrator, IntakeSpecialist, RecordsAnalyst, LienAnalyst, DisbursementApprover, ClaimantRole |
| POST | /settlement-programs/{pid}/_clock/set_current_utc | Advance the program's logical clock | ProgramAdministrator |
| POST | /settlement-programs/{pid}/tier-matrices | Create a tier matrix row | ProgramAdministrator |
| GET | /settlement-programs/{pid}/tier-matrices | List tier matrix rows | ProgramAdministrator, IntakeSpecialist, RecordsAnalyst, LienAnalyst, DisbursementApprover |
| GET | /settlement-programs/{pid}/tier-matrices/{tmid} | Get a tier matrix row | ProgramAdministrator, IntakeSpecialist, RecordsAnalyst, LienAnalyst, DisbursementApprover |
| POST | /settlement-programs/{pid}/tier-matrices/{tmid}/publish | Publish a matrix row, superseding overlapping published rows of the same category | ProgramAdministrator |
| POST | /settlement-programs/{pid}/claimants | Register a claimant | IntakeSpecialist |
| GET | /settlement-programs/{pid}/claimants | List claimants | ProgramAdministrator, IntakeSpecialist, RecordsAnalyst, LienAnalyst, DisbursementApprover |
| GET | /settlement-programs/{pid}/claimants/{clid} | Get a claimant | ProgramAdministrator, IntakeSpecialist, RecordsAnalyst, LienAnalyst, DisbursementApprover, ClaimantRole |
| POST | /settlement-programs/{pid}/claims | File a new claim | IntakeSpecialist |
| GET | /settlement-programs/{pid}/claims | List claims | ProgramAdministrator, IntakeSpecialist, RecordsAnalyst, LienAnalyst, DisbursementApprover |
| GET | /settlement-programs/{pid}/claims/{cid} | Get a claim | ProgramAdministrator, IntakeSpecialist, RecordsAnalyst, LienAnalyst, DisbursementApprover, ClaimantRole |
| POST | /settlement-programs/{pid}/claims/{cid}/screen-eligibility | Screen claim eligibility against program criteria | IntakeSpecialist |
| POST | /settlement-programs/{pid}/claims/{cid}/deny | Deny a claim at intake | IntakeSpecialist |
| POST | /settlement-programs/{pid}/claims/{cid}/withdraw | Withdraw a claim | ClaimantRole |
| POST | /settlement-programs/{pid}/claims/{cid}/medical-records | Upload a medical record | RecordsAnalyst |
| GET | /settlement-programs/{pid}/claims/{cid}/medical-records | List medical records for a claim | ProgramAdministrator, IntakeSpecialist, RecordsAnalyst, LienAnalyst |
| GET | /settlement-programs/{pid}/claims/{cid}/medical-records/{rid} | Get a medical record | ProgramAdministrator, IntakeSpecialist, RecordsAnalyst, LienAnalyst |
| POST | /settlement-programs/{pid}/claims/{cid}/medical-records/{rid}/accept | Accept a medical record | RecordsAnalyst |
| POST | /settlement-programs/{pid}/claims/{cid}/medical-records/{rid}/reject | Reject a medical record | RecordsAnalyst |
| POST | /settlement-programs/{pid}/claims/{cid}/verify-injury | Verify the qualifying injury | RecordsAnalyst |
| POST | /settlement-programs/{pid}/claims/{cid}/assign-tier | Assign tier via a published matrix row | ProgramAdministrator |
| POST | /settlement-programs/{pid}/claims/{cid}/appeals | File an appeal disputing the assigned tier | ClaimantRole |
| GET | /settlement-programs/{pid}/claims/{cid}/appeals | List appeals on a claim | ProgramAdministrator, IntakeSpecialist, LienAnalyst, ClaimantRole |
| GET | /settlement-programs/{pid}/claims/{cid}/appeals/{aid} | Get an appeal | ProgramAdministrator, IntakeSpecialist, LienAnalyst, ClaimantRole |
| POST | /settlement-programs/{pid}/claims/{cid}/appeals/{aid}/begin-review | Move appeal to UNDER_REVIEW | ProgramAdministrator |
| POST | /settlement-programs/{pid}/claims/{cid}/appeals/{aid}/uphold | Uphold appeal; re-tier claim | ProgramAdministrator |
| POST | /settlement-programs/{pid}/claims/{cid}/appeals/{aid}/deny | Deny appeal | ProgramAdministrator |
| POST | /settlement-programs/{pid}/claims/{cid}/appeals/{aid}/withdraw | Withdraw an appeal | ClaimantRole |
| POST | /settlement-programs/{pid}/claims/{cid}/liens | Identify a lien | LienAnalyst |
| GET | /settlement-programs/{pid}/claims/{cid}/liens | List liens on a claim | ProgramAdministrator, LienAnalyst, DisbursementApprover, ClaimantRole |
| GET | /settlement-programs/{pid}/claims/{cid}/liens/{lid} | Get a lien | ProgramAdministrator, LienAnalyst, DisbursementApprover, ClaimantRole |
| POST | /settlement-programs/{pid}/claims/{cid}/liens/{lid}/notify | Notify holder; computes provisional demand | LienAnalyst |
| POST | /settlement-programs/{pid}/claims/{cid}/liens/{lid}/begin-negotiation | Begin negotiation (also the return ramp from DISPUTED) | LienAnalyst |
| POST | /settlement-programs/{pid}/claims/{cid}/liens/{lid}/dispute | Claimant disputes an in-negotiation lien | ClaimantRole |
| POST | /settlement-programs/{pid}/claims/{cid}/liens/{lid}/resolve | Resolve a lien via negotiated or silent-holder path | LienAnalyst |
| POST | /settlement-programs/{pid}/claims/{cid}/liens/{lid}/waive | Waive a lien | LienAnalyst |
| POST | /settlement-programs/{pid}/claims/{cid}/finalize-liens | Mark liens resolved; precompute totals | LienAnalyst |
| POST | /settlement-programs/{pid}/claims/{cid}/prepare-disbursement | Reserve QSF and spawn disbursement rows | DisbursementApprover |
| GET | /settlement-programs/{pid}/claims/{cid}/disbursements | List disbursements for a claim | ProgramAdministrator, DisbursementApprover, ClaimantRole |
| GET | /settlement-programs/{pid}/claims/{cid}/disbursements/{did} | Get a disbursement | ProgramAdministrator, DisbursementApprover, ClaimantRole |
| POST | /settlement-programs/{pid}/claims/{cid}/disbursements/{did}/approve | Approve a pending disbursement (segregated from prepare caller) | DisbursementApprover |
| POST | /settlement-programs/{pid}/claims/{cid}/disbursements/{did}/release | Release an approved disbursement | DisbursementApprover |
| POST | /settlement-programs/{pid}/claims/{cid}/disbursements/{did}/void | Void a pending disbursement and refund QSF | DisbursementApprover |
| POST | /settlement-programs/{pid}/claims/{cid}/close | Close a disbursed claim and seal a closing statement | ProgramAdministrator |
| GET | /settlement-programs/{pid}/claims/{cid}/closing-statements | List closing statements for a claim | ProgramAdministrator, DisbursementApprover, ClaimantRole |
| GET | /settlement-programs/claimants/{id} | Flat single-claimant read (alias of nested GET) | ProgramAdministrator, IntakeSpecialist, RecordsAnalyst, LienAnalyst, DisbursementApprover, ClaimantRole |
| GET | /settlement-programs/claims/{id} | Flat single-claim read (alias of nested GET) | ProgramAdministrator, IntakeSpecialist, RecordsAnalyst, LienAnalyst, DisbursementApprover, ClaimantRole |
| GET | /settlement-programs/tier-matrices/{id} | Flat single-tier-matrix read (alias of nested GET) | ProgramAdministrator, IntakeSpecialist, RecordsAnalyst, LienAnalyst, DisbursementApprover |
| GET | /settlement-programs/medical-records/{id} | Flat single-medical-record read (alias of nested GET) | ProgramAdministrator, IntakeSpecialist, RecordsAnalyst, LienAnalyst |
| GET | /settlement-programs/liens/{id} | Flat single-lien read (alias of nested GET) | ProgramAdministrator, LienAnalyst, DisbursementApprover, ClaimantRole |
| GET | /settlement-programs/appeals/{id} | Flat single-appeal read (alias of nested GET) | ProgramAdministrator, IntakeSpecialist, LienAnalyst, ClaimantRole |
| GET | /settlement-programs/disbursements/{id} | Flat single-disbursement read (alias of nested GET) | ProgramAdministrator, DisbursementApprover, ClaimantRole |
| GET | /settlement-programs/closing-statements/{id} | Flat single-closing-statement read (alias of nested GET) | ProgramAdministrator, DisbursementApprover, ClaimantRole |
| GET | /settlement-programs/claimants | Flat list claimants; FK filters for reverse reachability | ProgramAdministrator, IntakeSpecialist, RecordsAnalyst, LienAnalyst, DisbursementApprover |
| GET | /settlement-programs/claims | Flat list claims; FK filters for reverse reachability | ProgramAdministrator, IntakeSpecialist, RecordsAnalyst, LienAnalyst, DisbursementApprover |
| GET | /settlement-programs/tier-matrices | Flat list tier matrices; FK filters for reverse reachability | ProgramAdministrator, IntakeSpecialist, RecordsAnalyst, LienAnalyst, DisbursementApprover |
| GET | /settlement-programs/medical-records | Flat list medical records; FK filters for reverse reachability | ProgramAdministrator, IntakeSpecialist, RecordsAnalyst, LienAnalyst |
| GET | /settlement-programs/liens | Flat list liens; FK filters for reverse reachability | ProgramAdministrator, LienAnalyst, DisbursementApprover, ClaimantRole |
| GET | /settlement-programs/appeals | Flat list appeals; FK filters for reverse reachability | ProgramAdministrator, IntakeSpecialist, LienAnalyst, ClaimantRole |
| GET | /settlement-programs/disbursements | Flat list disbursements; FK filters for reverse reachability | ProgramAdministrator, DisbursementApprover, ClaimantRole |
| GET | /settlement-programs/closing-statements | Flat list closing statements; FK filters for reverse reachability | ProgramAdministrator, DisbursementApprover, ClaimantRole |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|------------------|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_REQUEST | 400 |
| ERR_CLAIM_INVALID_STATE | 409 |
| ERR_CLAIM_NOT_WITHDRAWABLE | 409 |
| ERR_DUPLICATE_ACTIVE_CLAIM | 409 |
| ERR_ELIGIBILITY_DATE_ORDER | 422 |
| ERR_INELIGIBLE_INJURY | 422 |
| ERR_RECORD_ALREADY_REVIEWED | 409 |
| ERR_INSUFFICIENT_MEDICAL_RECORDS | 409 |
| ERR_NO_QUALIFYING_RECORD | 422 |
| ERR_NO_PUBLISHED_MATRIX | 409 |
| ERR_MATRIX_NOT_PUBLISHED | 409 |
| ERR_MATRIX_CATEGORY_MISMATCH | 422 |
| ERR_SEVERITY_OUT_OF_RANGE | 422 |
| ERR_APPEAL_ALREADY_OPEN | 409 |
| ERR_APPEAL_INVALID_STATE | 409 |
| ERR_LIEN_INVALID_STATE | 409 |
| ERR_UNRESOLVED_LIENS_EXIST | 409 |
| ERR_OPEN_APPEAL_BLOCKS_FINALIZE | 409 |
| ERR_HOLDER_WINDOW_OPEN | 422 |
| ERR_FINAL_EXCEEDS_ASSERTED | 422 |
| ERR_DISBURSEMENT_INVALID_STATE | 409 |
| ERR_SELF_APPROVAL_FORBIDDEN | 403 |
| ERR_DISBURSEMENTS_PENDING | 409 |
| ERR_NEGATIVE_NET_AWARD | 422 |
| ERR_QSF_INSUFFICIENT_FUNDS | 402 |
