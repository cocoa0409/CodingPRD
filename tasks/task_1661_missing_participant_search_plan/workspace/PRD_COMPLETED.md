# Missing Participant Plan Termination API — Product Requirements Document

## 1. Introduction

When a retirement plan sponsor terminates its plan, the plan is legally obligated to distribute every participant's benefit — including benefits owed to participants who can no longer be found. Uncashed distribution checks and undeliverable mail are the operational signals that a participant may be missing, and the Department of Labor expects a documented, escalating search protocol (commercial locator services, public-records searches, credit-bureau inquiries, and certified mail) before the plan may treat the participant as unfindable. Once the search protocol is exhausted, the plan must choose a destination for the benefit: a transfer to the PBGC Missing Participants Program or, as a last resort, a forfeiture that must later be restored — with earnings where the plan's restoration policy so requires — if the participant resurfaces.

This document specifies an API that administers the full lifecycle of a terminating defined contribution plan under these constraints: opening the termination case and issuing the statutory notices (notice of intent to terminate, interested-party notice for the IRS determination letter filing, blackout advisory for the recordkeeper transition, and the distribution notice that starts the default-treatment clock), running the blackout period that accompanies the recordkeeper change, collecting and processing distribution elections, applying balance-tiered default treatment to non-responders, sweeping for stale uncashed checks, escalating missing-participant searches through their mandated four-step protocol, and finally reconciling, filing for an IRS determination letter, and closing the case under independent fiduciary sign-off.

Every step is timestamped against a server-side logical clock (whose startup value is exactly 2026-08-01T00:00:00Z), so statutory windows — measured in whole calendar days — are deterministic and auditable. The system is built for fiduciary scrutiny: a segregation-of-duties rule separates the operator who exhausts a search from the fiduciary who approves its disposition, and every consequential decision (search protocol summary, forfeiture rationale, PBGC transfer rationale, closure sign-off) lands in an append-only fiduciary log.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifying the acting user and `X-User-Role` naming the acting role. The recognized role strings, spelled exactly, are `PlanAdministrator`, `IndependentFiduciary`, `Recordkeeper`, and `Participant`. A request missing either header, presenting an empty or whitespace-only `X-User-ID`, or presenting a role outside this enumeration, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Role identity semantics are as follows. When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting `Participant` record; ownership checks on any resource that references a `Participant` compare the resource's foreign-key field to `X-User-ID`. In particular, a `Participant` submitting a distribution election must send a payload whose `participant_id` equals `X-User-ID`, and any mismatch is rejected with `ERR_PARTICIPANT_OWNERSHIP_VIOLATION` (HTTP 403); that election submission is the only ownership check in the API — read endpoints authorized for the `Participant` role enforce role authorization only, never ownership. When `X-User-Role` is `PlanAdministrator`, `IndependentFiduciary`, or `Recordkeeper`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where the workflow demands (for example, as `exhausted_by_user_id` on a `MissingSearchCase` at exhaustion, or as `author_user_id` and `author_role` on a `FiduciaryLogEntry`) but does not compare it to any entity's `id` — except for the segregation-of-duties check described in §2.7, which deliberately compares the acting fiduciary's `X-User-ID` to a recorded `exhausted_by_user_id`.

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

All list endpoints accept the query parameters `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter defaults to 0. A `limit` or `offset` that does not parse as an integer, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). List responses are sorted by `created_at` ascending, ties broken by creation sequence with the earliest-created row first. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Most persisted resources carry the common properties `id`, `created_at`, `updated_at`, and `version`. The `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps rendered with three fractional digits. `version` is an integer that increments on every mutation of the entity's stored fields. Fields marked as computed in this document are derived on read and never stored; an entity's `version` increments only when a stored (input or system) field of that entity changes, with `updated_at` refreshing alongside. Creating a child row does not bump the parent's `version` unless the writing operation's stated side effects say so — the two OCC-guarded write operations described in §2.6 always do.

Two resources are append-only logs and deliberately carry only `id` and `created_at`: `SearchAttempt` and `FiduciaryLogEntry` have neither `updated_at` nor `version`.

Time in this system is governed by a logical clock, not the wall clock. Before any explicit set, the clock reads exactly 2026-08-01T00:00:00Z. A `PlanAdministrator` may advance (or move) the clock to any ISO 8601 instant via an admin-only test-driving capability that accepts a `to_iso8601` instant and returns the resulting `current_utc` (the response carries the submitted `to_iso8601` value); non-monotonic moves are permitted, and the clock never falls back to wall-clock time. After every set, a stale-check sweep runs over all issued lump-sum-check payouts, as described in §3.6. Every rule in this document that speaks of "days" measures whole calendar days — the number of days between two instants is the floor of their difference divided by 86,400 seconds — and every window stated as inclusive is inclusive of both endpoints unless explicitly described as strictly-greater.

### 2.5. Monetary Precision and Rounding

All monetary amounts are integers in cents. Every rounding in the system rounds half up to whole cents. Percentages such as withholding rates and the earnings adjustment rate are applied to cent values and then rounded half up; day counts are whole calendar days. No rule uses approximate arithmetic: boundaries stated as "at least" or "at most" are inclusive, and comparisons described as strictly-greater are strict.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and both always bump the guarded parent's `version` as a side effect.

Issuing a participant notice requires the request body to carry `expected_termination_case_version`, holding the `version` of the `TerminationCase` as the client last observed it. If another writer has advanced the case's `version` since that read — for example by reissuing a notice, which legitimately supersedes the live notice of the same type — the issuance is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the writer to re-read before superseding.

Submitting a distribution election requires the request body to carry `expected_participant_version`, holding the `version` of the electing `Participant` as the client last observed it. If the participant's version has advanced — whether because a newer election legitimately superseded the previously submitted one, or because a cascade such as the vesting re-computation, a contact flag, or a forfeiture restoration mutated the participant — the submission is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field. The version check is evaluated after existence checks and before business rules.

### 2.7. Segregation of Duties and Fiduciary Documentation

A single operator must not both exhaust a missing-participant search and dispose of that participant's benefit. When a search case is escalated from its final step to `EXHAUSTED`, the acting `PlanAdministrator`'s `X-User-ID` is recorded as the case's `exhausted_by_user_id`. Subsequently, any request to create a PBGC transfer or a forfeiture for that participant whose `X-User-ID` equals the recorded `exhausted_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403).

Dispositions and closure are additionally gated on documentation. Creating a PBGC transfer or a forfeiture requires that a `FiduciaryLogEntry` with `entry_type` `SEARCH_PROTOCOL_SUMMARY` exists whose `related_entity_id` equals the id of the exhausted search case; closing a termination case requires that at least one `FiduciaryLogEntry` with `entry_type` `CLOSURE_SIGNOFF` exists for the case. Absence of the required entry is rejected with `ERR_FIDUCIARY_DOC_MISSING` (HTTP 422).

### 2.8. Fund Conservation and Resolution Posture

The termination case maintains a conserved ledger. At every moment, `total_plan_assets_cents` equals the sum of `paid_out_cents`, `pbgc_transferred_cents`, `forfeited_cents`, `expense_paid_cents`, and `remaining_undistributed_cents`; this invariant is checked after every money-moving transition — payout clear or void, PBGC confirmation, forfeiture creation, forfeiture restoration, expense allocation, and effectuation. Forfeiture creation and its later restoration are a compensating pair: creation moves the forfeited amount from `remaining_undistributed_cents` to `forfeited_cents`, and a nominal restoration moves the same amount back, leaving the conserved total unchanged.

A parallel conservation holds over participant counts: `total_participant_count` always equals `resolved_participant_count` plus the number of participants whose `distribution_status` is `PENDING_ELECTION`, `ELECTION_SUBMITTED`, `ELECTION_ACCEPTED`, or `RESTORED`. A payout clearing moves one participant into the resolved set; a forfeiture restoration moves one back out. The boolean `all_participants_resolved` is true exactly when `total_participant_count` is greater than zero and `resolved_participant_count` equals `total_participant_count` — so a case with no participants is never "all resolved". `missing_participant_count` counts participants whose `locate_status` is `MISSING`, and `blackout_active` is true exactly when any `BlackoutPeriod` of the case is `ACTIVE`.

### 2.9. Validation Order

Every write request passes through a fixed sequence of rejection layers, and the layering is observable: an earlier failure masks later ones. First, the two auth headers are checked (missing or unrecognised headers yield `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, role authorization is checked (`ERR_FORBIDDEN_ROLE`, or `ERR_PARTICIPANT_OWNERSHIP_VIOLATION` for a `Participant` submitting an election for someone else). Third, the request body shape is validated — required fields present, types correct, enum values in range, numeric constraints holding, no undeclared fields (`ERR_INVALID_REQUEST`), with an explicit JSON null on an optional field treated as if the field were omitted, and with the fiduciary narrative length check reported separately as `ERR_NARRATIVE_TOO_SHORT`. Fourth, path resource identifiers are resolved left-to-right (`ERR_NOT_FOUND`), and body foreign-key references such as `termination_case_id` and `participant_id` are resolved (`ERR_REFERENCE_NOT_FOUND`). Fifth, the optimistic-concurrency version check runs (`ERR_STALE_VERSION`). Sixth, from-state gates run — case status, participant flag and missing gates, search-case step gates, election and payout states, transfer and DLR states, blackout states. Seventh, segregation of duties (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`). Eighth, fiduciary documentation (`ERR_FIDUCIARY_DOC_MISSING`). Ninth, structural constraints (blackout overlap, search-method match, attempt chronology, single-open-transfer, single-active-forfeiture, single-open-DLR, expense-eligibility). Tenth, the statutory temporal windows. Eleventh, cross-entity referential rules (covering notices, search exhaustion, all-resolved posture). Twelfth and last, money rules — so a request that is both temporally invalid and fiscally invalid reports the temporal failure first.

### 2.10. Nested Resource Retrieval and Filtering

Where an endpoint path contains multiple resource identifiers, they are validated left-to-right: the first identifier is resolved before the second, and the first missing identifier produces the `ERR_NOT_FOUND` rejection. List endpoints support filters matching the foreign keys declared in §4 — including `termination_case_id`, `participant_id`, `active_search_case_id`, `locate_status`, `distribution_status`, `notice_type`, `superseded_by_id`, `status`, and `entry_type` — each of which narrows the returned collection to rows whose corresponding field equals the supplied value, on top of the envelope pagination parameters `limit` and `offset`. The literal filter value `null` (or an empty value) matches rows whose field is null — so `superseded_by_id=null` selects exactly the live notices — and query parameters beyond the declared filters and pagination parameters are ignored.

## 3. Business Logic & Workflows

### 3.1. Opening the Termination Case and the Notice Program

A `PlanAdministrator` opens a plan termination by creating a `TerminationCase` with the plan's legal `plan_name`, the sponsor's `sponsor_ein` (exactly nine digits), the `plan_number` (exactly three digits), the `proposed_termination_date` against which all notice windows and effectuation are measured, and an optional `restoration_policy` of `NOMINAL` or `EARNINGS_ADJUSTED` which defaults to `NOMINAL` when omitted. The new case starts in `DRAFT` status with all counters and ledger fields at zero.

Participants join the census next. Adding a participant requires the owning case's `termination_case_id` in the payload along with `full_name`, `ssn` (exactly nine digits — the credit-bureau search step relies on it), `mailing_address`, `account_balance_cents` (which may not be negative), and `vested_pct` between 0 and 100 inclusive. A new participant starts with `locate_status` `UNVERIFIED` and `distribution_status` `PENDING_ELECTION`, and the system immediately derives `vested_balance_cents` as the account balance multiplied by the vesting percentage and divided by 100, rounded half up to whole cents, and `net_distributable_cents` as `vested_balance_cents` minus `termination_expense_share_cents` (which starts at zero). The census closes as distributions begin: a participant may only be added while the case is `DRAFT`, `NOTICE_OF_INTENT_ISSUED`, or `TERMINATION_EFFECTIVE`, and a create attempted once the case has reached `DISTRIBUTION_IN_PROGRESS` or beyond is rejected with `ERR_CASE_CENSUS_FROZEN` (HTTP 409). When the case is already `TERMINATION_EFFECTIVE` at the time of the add, the participant is stored with `vested_pct` forced to 100 regardless of the supplied value, and such a late add does not alter the ledger snapshot taken at effectuation: `total_plan_assets_cents` and `remaining_undistributed_cents` are unchanged by it.

The case leaves `DRAFT` through the notice of intent to terminate. Issuing a notice creates a `ParticipantNotice` carrying the case's `termination_case_id`, a `notice_type` of `NOIT`, `INTERESTED_PARTY`, `BLACKOUT_ADVISORY`, or `DISTRIBUTION`, and an `action_effective_date` naming the date of the noticed action — the termination date for a NOIT, the blackout start for a `BLACKOUT_ADVISORY`, the distribution commencement for a `DISTRIBUTION` notice, and the intended filing date for an `INTERESTED_PARTY` notice. Every issuance records the clock time as `issued_at` and supersedes the prior live notice of the same `notice_type` on the same case by writing the new notice's id into the superseded notice's `superseded_by_id` (which is null while a notice is the live one). Issuance is one of the two OCC-guarded writes: the payload must carry `expected_termination_case_version`, a stale value is rejected with `ERR_STALE_VERSION`, and a successful issuance increments the case's `version` by one.

For a NOIT specifically, the case must be `DRAFT` or `NOTICE_OF_INTENT_ISSUED` (otherwise `ERR_CASE_INVALID_STATE`, HTTP 409); the `action_effective_date` must equal the case's `proposed_termination_date`, failing which the issuance is rejected with `ERR_NOIT_DATE_MISMATCH` (HTTP 422); and the issuance clock time must fall within the window from 90 days before the proposed termination date through 60 days before it, inclusive by whole calendar days — an issuance outside that window is rejected with `ERR_NOIT_TIMING_WINDOW` (HTTP 422). A first NOIT transitions the case `DRAFT → NOTICE_OF_INTENT_ISSUED`; a reissued NOIT keeps the case in `NOTICE_OF_INTENT_ISSUED` while superseding the previous NOIT under the same date and timing checks.

An `INTERESTED_PARTY` notice may be issued in any case status except `CLOSED`, and its `action_effective_date` names the intended IRS filing date; the window that makes it a valid covering notice is described with the determination letter workflow in §3.7. A `BLACKOUT_ADVISORY` notice likewise may be issued in any status except `CLOSED`, but its timing is pinned to the blackout it covers, as described in §3.5. A `DISTRIBUTION` notice may only be issued while the case is `TERMINATION_EFFECTIVE` (otherwise `ERR_CASE_INVALID_STATE`), and its issuance pins the case's computed `default_treatment_date` to the non-superseded `DISTRIBUTION` notice's `action_effective_date` plus 30 days — null until such a notice exists, and recomputed on supersede.

### 3.2. Effectuating the Termination and Beginning Distributions

Once the notice of intent is outstanding and the calendar has run, a `PlanAdministrator` effectuates the termination. The case must be `NOTICE_OF_INTENT_ISSUED` (otherwise `ERR_CASE_INVALID_STATE`) and the current clock must be at or after the `proposed_termination_date`, failing which the call is rejected with `ERR_TERMINATION_DATE_NOT_REACHED` (HTTP 409). Effectuation is a fan-out event: every participant's `vested_pct` is forced to 100, each participant's `vested_balance_cents` and `net_distributable_cents` are recomputed, and each participant's `version` increments. Simultaneously the case snapshots its ledger: `total_plan_assets_cents` becomes the sum of `account_balance_cents` over all participants, and `remaining_undistributed_cents` initializes to the same total. The case arrives at `TERMINATION_EFFECTIVE`.

Distributions begin with a separate deliberate act. Beginning distributions requires the case to be `TERMINATION_EFFECTIVE` (otherwise `ERR_CASE_INVALID_STATE`), requires a non-superseded `DISTRIBUTION` notice to exist for the case (otherwise `ERR_DISTRIBUTION_NOTICE_REQUIRED`, HTTP 422), and requires that no `BlackoutPeriod` of the case is `SCHEDULED` or `ACTIVE` (otherwise `ERR_BLACKOUT_TRANSITION_PENDING`, HTTP 409). The transition to `DISTRIBUTION_IN_PROGRESS` takes the `default_treatment_date` already pinned by the distribution notice, and from this point elections, default treatments, transfers, and forfeitures become available.

Later, when every participant's money lifecycle has terminated, advancing the case `DISTRIBUTION_IN_PROGRESS → FINAL_RECONCILIATION` requires `all_participants_resolved` to be true, failing which the call is rejected with `ERR_PARTICIPANTS_NOT_ALL_RESOLVED` (HTTP 409) — and note that the empty census never satisfies this, since `all_participants_resolved` demands a positive `total_participant_count`. There is no separate residual-balance precondition: every money movement in the system drains exactly the participant's payable amount (with sponsor make-whole where a frozen benefit exceeds the participant's net), so `remaining_undistributed_cents` is zero by construction once all participants are resolved. Reconciliation is not a point of no return — a forfeited participant who resurfaces reopens the distribution phase, as §3.4 describes.

### 3.3. Contact Flags, Missing Declarations, and the Participant's Two State Dimensions

Each participant carries two independent state dimensions on the same row: `locate_status` (the contact lifecycle: `UNVERIFIED`, `FLAGGED_UNCASHED`, `FLAGGED_UNDELIVERABLE`, `MISSING`, `LOCATED`) and `distribution_status` (the money lifecycle: `PENDING_ELECTION`, `ELECTION_SUBMITTED`, `ELECTION_ACCEPTED`, `PAID_OUT`, `AUTO_ROLLED_OVER`, `PBGC_TRANSFERRED`, `FORFEITED`, `RESTORED`). A transition on one dimension never changes the other unless a stated cascade says so. The terminal money states are `PAID_OUT`, `AUTO_ROLLED_OVER`, and `PBGC_TRANSFERRED`; `FORFEITED` is a resolved-but-reversible state, since restoration returns the participant to `RESTORED` and further processing.

Contact trouble surfaces through the `Recordkeeper`. Recording a contact flag with `flag_type` `UNCASHED_CHECK` moves a participant whose `locate_status` is `UNVERIFIED` or `LOCATED` to `FLAGGED_UNCASHED`; the same flag with `flag_type` `UNDELIVERABLE_MAIL` moves such a participant to `FLAGGED_UNDELIVERABLE`. A flag recorded from any other `locate_status` is rejected with `ERR_INVALID_FLAG_TRANSITION` (HTTP 409). Either transition stamps `flagged_at` with the clock time. An optional `evidence_note` may accompany the flag; the note is accepted but not persisted on the participant record. The system itself raises the uncashed-check signal: when the stale-check sweep (§3.6) marks a payout `STALE_UNCASHED`, the participant's `locate_status` flips to `FLAGGED_UNCASHED` with `flagged_at` set — but only if the participant was `UNVERIFIED` at that moment; otherwise the locate dimension is left unchanged. Flags are cleared by the `Recordkeeper` with a matching `flag_type`: clearing `UNCASHED_CHECK` from `FLAGGED_UNCASHED` (the check finally cleared, or the address was re-confirmed) and clearing `UNDELIVERABLE_MAIL` from `FLAGGED_UNDELIVERABLE` (a verified new address is on file) both return the participant to `UNVERIFIED`; a clear whose `flag_type` does not match the current flag is rejected with `ERR_INVALID_FLAG_TRANSITION`.

A flagged participant is declared missing by a `PlanAdministrator`. Declaration requires `locate_status` to be `FLAGGED_UNCASHED` or `FLAGGED_UNDELIVERABLE` — from anywhere else the call fails with `ERR_PARTICIPANT_NOT_FLAGGED` (HTTP 409), and because an open search case implies the participant is already `MISSING`, this gate also blocks re-declaration while a case is open. One further gate looks backward: at most one `MissingSearchCase` ever exists for a participant, and if that case has been driven to `EXHAUSTED` the declaration is rejected with `ERR_SEARCH_CASE_EXHAUSTED_REDECLARE` (HTTP 409) — an exhausted participant's disposition must proceed, not restart. A successful declaration stamps `declared_missing_at` with the clock time and arms the search machinery: if no prior `MissingSearchCase` exists, one is created in `STEP1_COMMERCIAL_LOCATOR` with `opened_at` set to now; if the latest case is `RESOLVED`, it reopens to `STEP1_COMMERCIAL_LOCATOR` with its `resolved_at` cleared to null while `opened_at` is preserved from the original opening. Either way the participant's `active_search_case_id` is set to that search case's id (it is null when no case exists or the latest case is `RESOLVED`), and the participant's `version` increments.

Location closes the loop. A `PlanAdministrator` may mark a `MISSING` participant located — optionally carrying a `verified_address`, which likewise is accepted but not persisted — and a search attempt recording `LOCATED` has the same effect; from any other `locate_status` the direct locate is rejected with `ERR_PARTICIPANT_NOT_MISSING` (HTTP 409). Location stamps `located_at`, transitions the open `MissingSearchCase` (if any) to `RESOLVED` with `resolved_at` set, and clears the participant's `active_search_case_id` to null; an `EXHAUSTED` search case is not open, so locating a participant whose active case is `EXHAUSTED` leaves the case `EXHAUSTED` and leaves `active_search_case_id` referencing it. And when the located participant's `distribution_status` is `FORFEITED`, the locate fires a second cascade hop: the distribution dimension flips `FORFEITED → RESTORED`, which in turn restores the forfeiture itself — the full chain is detailed in §3.4.

### 3.4. The Search Protocol, PBGC Transfers, and Forfeitures

The `MissingSearchCase` is a cyclic four-step protocol. From `STEP1_COMMERCIAL_LOCATOR` it escalates to `STEP2_PUBLIC_RECORDS`, then to `STEP3_CREDIT_BUREAU`, then to `STEP4_CERTIFIED_MAIL`, and finally to the terminal `EXHAUSTED`. Every escalation is performed by a `PlanAdministrator` and is gated the same way: the case must be in the expected step (escalating a `RESOLVED` or `EXHAUSTED` case is rejected with `ERR_SEARCH_CASE_NOT_ESCAPABLE`, HTTP 409), and at least one recorded `SearchAttempt` on the case must exist whose `method` matches the current step and whose `outcome` is `NO_RESULT` — without it, the escalation fails with `ERR_NO_ATTEMPT_ON_CURRENT_STEP` (HTTP 409). The attempt's `method` is one of `COMMERCIAL_LOCATOR`, `PUBLIC_RECORDS`, `CREDIT_BUREAU`, or `CERTIFIED_MAIL` and must equal the case's current step; a mismatched method is rejected with `ERR_SEARCH_METHOD_MISMATCH` (HTTP 422). Recording an attempt also requires the case to be in a step state — attempts on a `RESOLVED` or `EXHAUSTED` case fail with `ERR_SEARCH_CASE_NOT_OPEN` (HTTP 409) — and the stored row carries the owning case's id as `search_case_id` along with `vendor_name`, `attempted_at`, `outcome` (`NO_RESULT` or `LOCATED`), and optional `notes`. Attempts are chronological: `attempted_at` must be at or after the case's `opened_at`, at or before the current clock, and at or after every prior attempt's `attempted_at` on the same case, else `ERR_ATTEMPT_TIMESTAMP_INVALID` (HTTP 422). Each recorded attempt increments the case's `attempt_count`, the count of `SearchAttempt` rows for the case.

Certified mail carries two statutory timing rules. A `CERTIFIED_MAIL` attempt may not fall inside the 15-day trailing buffer of a previous `CERTIFIED_MAIL` attempt on the same case — an `attempted_at` earlier than the prior certified-mail attempt's `attempted_at` plus 15 days is rejected with `ERR_CERTIFIED_MAIL_WINDOW_ACTIVE` (HTTP 409). And the final escalation `STEP4_CERTIFIED_MAIL → EXHAUSTED` additionally requires that the current clock has reached the latest certified-mail attempt's `attempted_at` plus 15 days (latest by `attempted_at`, ties broken by latest `created_at`); escalating earlier is rejected with `ERR_CERTIFIED_MAIL_RESPONSE_WINDOW_OPEN` (HTTP 409). Successful exhaustion stamps `exhausted_at` with the clock time, records the acting operator in `exhausted_by_user_id`, and freezes `exhaustion_snapshot_cents` to the participant's `net_distributable_cents` at that moment — the snapshot that one of the PBGC amount bases later draws on.

When an attempt comes back `LOCATED`, the case moves from whichever step it occupied to `RESOLVED` with `resolved_at` stamped and the participant's `active_search_case_id` cleared — the same effects as a direct locate. A later re-declaration of the same participant reopens the `RESOLVED` case to `STEP1_COMMERCIAL_LOCATOR`, clears `resolved_at` to null, and restarts the protocol from step one; the reopen preserves the case's recorded attempts, and any attempt on the case — including one recorded before the reopen — satisfies the escalation gate of its matching step.

With the search exhausted, two dispositions are available to the `IndependentFiduciary`, and both share the same front gates. The participant's `locate_status` must be `MISSING` (otherwise `ERR_PARTICIPANT_NOT_MISSING`, HTTP 409) and `distribution_status` must be `PENDING_ELECTION` (otherwise `ERR_ELECTION_INVALID_STATE`, HTTP 409); the case must be `DISTRIBUTION_IN_PROGRESS` or `FINAL_RECONCILIATION` (otherwise `ERR_CASE_INVALID_STATE`); the participant's active search case must be `EXHAUSTED`, otherwise `ERR_SEARCH_PROTOCOL_INCOMPLETE` (HTTP 409); the segregation-of-duties rule of §2.7 bars the exhauster from approving; and the `SEARCH_PROTOCOL_SUMMARY` fiduciary log entry referencing the exhausted search case must exist. These gates evaluate in the §2.9 order — so, for example, a request from the wrong role reports `ERR_FORBIDDEN_ROLE` before any state check runs, and a segregation violation surfaces before the documentation check; within the shared from-state layer, the case-status check runs before the locate-status check.

A PBGC transfer submits the participant's benefit to the PBGC Missing Participants Program. The create payload carries `participant_id` and an `amount_basis` of `SUBMISSION_NET` or `EXHAUSTION_SNAPSHOT`. Under `SUBMISSION_NET`, the computed `amount_cents` is the participant's `net_distributable_cents` at the moment of creation; under `EXHAUSTION_SNAPSHOT`, it is the search case's frozen `exhaustion_snapshot_cents`. The two diverge exactly when an expense allocation has debited the participant between exhaustion and submission — the snapshot variant then produces the larger amount. Once created, `amount_cents` is frozen and `submitted_at` records the clock time. A participant with a zero transferable amount — `net_distributable_cents` (or the exhaustion snapshot, per the basis) equal to 0 — is rejected with `ERR_ZERO_BALANCE_TRANSFER` (HTTP 422), and a participant who already has a `SUBMITTED` transfer is rejected with `ERR_PBGC_TRANSFER_ALREADY_OPEN` (HTTP 409).

The transfer then awaits the PBGC's answer, recorded by a `PlanAdministrator`. Confirmation requires the transfer to be `SUBMITTED` (otherwise `ERR_PBGC_TRANSFER_NOT_SUBMITTED`, HTTP 409) and re-checks that the case is `DISTRIBUTION_IN_PROGRESS` or `FINAL_RECONCILIATION` (otherwise `ERR_CASE_INVALID_STATE`). Acceptance stamps `confirmed_at`, moves the transfer `SUBMITTED → ACCEPTED`, moves the participant's `distribution_status` to `PBGC_TRANSFERRED`, and settles the ledger with a sponsor make-whole: the excess is the amount by which the frozen `amount_cents` exceeds the participant's current `net_distributable_cents`, floored at zero; when the excess is positive, the case's `sponsor_contribution_cents` and `total_plan_assets_cents` each increase by the excess — the sponsor funds the frozen benefit above the participant's post-expense net. Then `pbgc_transferred_cents` increases by `amount_cents`, `remaining_undistributed_cents` becomes its prior value minus `amount_cents` plus the excess, and `resolved_participant_count` is recomputed. Recording a rejection instead requires the same `SUBMITTED` state (otherwise `ERR_PBGC_TRANSFER_NOT_SUBMITTED`) and carries a mandatory `reason` (stored as `rejection_reason`); the transfer moves to `REJECTED` while the participant remains `MISSING` with `distribution_status` `PENDING_ELECTION` — the plan must then elect forfeiture or make a fresh PBGC submission.

The forfeiture is the last-resort alternative. Its creation payload carries `participant_id` and a `rationale`, and the shared front gates above apply, plus a singularity rule: a participant who already has a `RECORDED` forfeiture is rejected with `ERR_FORFEITURE_ALREADY_RECORDED` (HTTP 409), and the zero-balance rule rejects with `ERR_ZERO_BALANCE_TRANSFER`. Unlike a transfer creation, a forfeiture creation evaluates the segregation-of-duties, documentation, and singularity gates ahead of the distribution-state gate — a repeat forfeiture for a participant who already has a `RECORDED` forfeiture (and is therefore `FORFEITED`) reports `ERR_FORFEITURE_ALREADY_RECORDED`, not `ERR_ELECTION_INVALID_STATE`; the PBGC transfer creation keeps the strict §2.9 order with the distribution-state gate in its from-state layer. A created forfeiture is `RECORDED` with `forfeited_amount_cents` frozen to the participant's `net_distributable_cents` at creation; the participant's `distribution_status` moves to `FORFEITED`, the case's `forfeited_cents` increases by the forfeited amount, `remaining_undistributed_cents` decreases by it, and `resolved_participant_count` is recomputed — forfeited participants count as resolved for reconciliation purposes.

Restoration is the system-driven unwind, chained as four hops from a single locate event. When a `MISSING` participant is located while `FORFEITED`, hop two flips the participant `FORFEITED → RESTORED`; hop three flips the participant's `RECORDED` forfeiture to `RESTORED`, stamping `restored_at` and computing `restoration_amount_cents` per the case's `restoration_policy`, with elapsed time measured in whole calendar days from the forfeiture's `created_at` to now, floored at zero days (the logical clock may move non-monotonically). Under `NOMINAL`, the restoration amount equals the forfeited amount exactly. Under `EARNINGS_ADJUSTED`, the restoration amount is the forfeited amount plus simple earnings: the forfeited amount multiplied by an annual rate of 4.5 percent, multiplied by the elapsed whole days, divided by 365, rounded half up to whole cents, added to the forfeited amount — strictly larger than nominal whenever at least one day has elapsed. Hop four repairs the ledger: `forfeited_cents` decreases by the forfeited amount and `remaining_undistributed_cents` increases by it; under `EARNINGS_ADJUSTED` the earnings part (the restoration amount minus the forfeited amount) additionally increases `sponsor_contribution_cents` and `total_plan_assets_cents`, raises `remaining_undistributed_cents` by the same earnings part, and adds it to the participant's `restoration_credit_cents`, where it waits to be paid out with the participant's next payout. Finally `resolved_participant_count` is recomputed — the restored participant leaves the resolved set. Each cascade hop that changes the participant's stored fields increments its `version` separately, so locating a `FORFEITED` participant advances the participant's `version` by two (the locate itself, then the `FORFEITED → RESTORED` flip), and the earnings-credit accrual adds no further increment.

A case in `FINAL_RECONCILIATION` containing such a restored participant may be moved back to `DISTRIBUTION_IN_PROGRESS` by a `PlanAdministrator` — the revert edge that a resurfaced forfeited participant forces. This reopen requires at least one participant in `RESTORED`, failing which the call is rejected with `ERR_NO_REOPENABLE_PARTICIPANT` (HTTP 409). A restored participant then re-enters the election workflow under exactly the same rules as a `PENDING_ELECTION` participant.

### 3.5. The Recordkeeper Transition and Blackout Periods

Switching recordkeepers mid-termination imposes a blackout during which participants cannot direct their accounts. A `PlanAdministrator` schedules a `BlackoutPeriod` with the case's `termination_case_id`, a `start_at` (inclusive), an `end_at` (exclusive — the window is the half-open interval from `start_at` up to but not including `end_at`, and `end_at` must be strictly after `start_at` or the create fails shape validation), and the `outgoing_recordkeeper` and `incoming_recordkeeper` names. Scheduling is permitted in any case status except `CLOSED` (otherwise `ERR_CASE_INVALID_STATE`). The new period is `SCHEDULED`. Blackout windows on the same case may not intersect: a new half-open window overlapping an existing one is rejected with `ERR_BLACKOUT_WINDOW_OVERLAP` (HTTP 409), while pure adjacency — a new `start_at` exactly equal to an existing window's `end_at` — is allowed.

The advisory notice runs ahead of the window. A `BLACKOUT_ADVISORY` notice's `action_effective_date` is the blackout start, and its issuance is lawful only when a `SCHEDULED` blackout exists on the case whose `start_at` equals that `action_effective_date` and the issuance clock time falls within the window from 60 days before the start through 30 days before it, inclusive by whole calendar days; an issuance failing either half is rejected with `ERR_BLACKOUT_NOTICE_WINDOW` (HTTP 422), and issuance without a matching `SCHEDULED` blackout also fails the from-state gate with `ERR_BLACKOUT_NOT_SCHEDULED` (HTTP 409).

Activation is the `Recordkeeper`'s act and requires the period to be `SCHEDULED` (otherwise `ERR_BLACKOUT_NOT_SCHEDULED`), the current clock to satisfy being at or after `start_at` and strictly before `end_at` (otherwise `ERR_BLACKOUT_NOT_IN_WINDOW`, HTTP 409), and a non-superseded `BLACKOUT_ADVISORY` notice to exist on the case whose `action_effective_date` equals the period's `start_at` (otherwise `ERR_BLACKOUT_NOTICE_MISSING`, HTTP 422) — that notice's own 30-to-60-day window having been enforced at its issuance. Activation stamps `activated_at`, recomputes the case's `blackout_active` to true, and from that moment new distribution elections are blocked.

Completion, also by the `Recordkeeper`, requires the period to be `ACTIVE` (otherwise `ERR_BLACKOUT_NOT_SCHEDULED`) and the current clock to be at or after `end_at` (otherwise `ERR_BLACKOUT_NOT_ENDED`, HTTP 409). Completion stamps `completed_at`, recomputes `blackout_active` to false, and releases the queue: every payout of the case sitting in `PREPARED` moves to `ISSUED` with `issued_at` set to the completion clock time. Because begin-distributions and case closure both refuse to run while a blackout is `SCHEDULED` or `ACTIVE` (`ERR_BLACKOUT_TRANSITION_PENDING`), the recordkeeper transition brackets the distribution phase rather than overlapping its edges.

### 3.6. Elections, Payouts, Withholding, and the Stale-Check Sweep

Once the case is `DISTRIBUTION_IN_PROGRESS`, participants direct their benefits through elections. Submitting a `DistributionElection` — by the `Participant` themself or by a `PlanAdministrator` on their behalf — carries `participant_id`, an `election_method` of `LUMP_SUM_CHECK`, `DIRECT_ROLLOVER_IRA`, or `DIRECT_ROLLOVER_QUALIFIED_PLAN`, an optional `destination_detail` for rollover institution or mailing instructions, and the OCC field `expected_participant_version` (§2.6). The gates: the case must be `DISTRIBUTION_IN_PROGRESS` (otherwise `ERR_CASE_INVALID_STATE`); the participant's `locate_status` must not be `MISSING` (otherwise `ERR_PARTICIPANT_MISSING_BLOCKS_ELECTION`, HTTP 409 — a missing participant goes through the search protocol instead of electing); no `BlackoutPeriod` of the case may be `ACTIVE` (otherwise `ERR_BLACKOUT_ACTIVE_ELECTIONS_BLOCKED`, HTTP 409); and the participant's `distribution_status` must be `PENDING_ELECTION`, `ELECTION_SUBMITTED`, or `RESTORED` (otherwise `ERR_ELECTION_INVALID_STATE`). These gates evaluate in the §2.9 sequence with the from-state gates first: the case-status and election-state checks precede the missing and blackout checks — a submission whose participant is both in a non-electable distribution state and `MISSING` reports `ERR_ELECTION_INVALID_STATE` — and the blackout-active check runs last. A successful submission creates the election in `SUBMITTED`, supersedes any prior `SUBMITTED` election of the same participant (`SUBMITTED → SUPERSEDED`), moves the participant's `distribution_status` to `ELECTION_SUBMITTED`, and increments the participant's `version` by one.

A `PlanAdministrator` then adjudicates. Acceptance requires the election to be `SUBMITTED` (otherwise `ERR_ELECTION_INVALID_STATE`) and the participant not `MISSING` (otherwise `ERR_PARTICIPANT_MISSING_BLOCKS_ELECTION`). Acceptance moves the election `SUBMITTED → ACCEPTED`, the participant to `ELECTION_ACCEPTED`, and creates the `Payout` with `source` `ELECTION` and a back-reference in `distribution_election_id` (null for payouts created by default treatment). The payout's `gross_cents` is the participant's `net_distributable_cents` at that moment plus any `restoration_credit_cents` the participant carries — and creating the payout consumes the credit, resetting `restoration_credit_cents` to zero. Withholding is computed at creation: when the method is `LUMP_SUM_CHECK` and the gross is at least 20000 cents (200.00 dollars — at or above the floor, withhold; below it, zero), `withholding_cents` is 20 percent of the gross rounded half up to whole cents; in every other case `withholding_cents` is zero. `net_cents` is the gross minus the withholding. The payout's initial status depends on the case's blackout posture: `PREPARED` when `blackout_active` is true, otherwise `ISSUED` with `issued_at` stamped. Rejection, instead, requires the election to be `SUBMITTED` (otherwise `ERR_ELECTION_INVALID_STATE`), carries a mandatory `reason`, moves the election `SUBMITTED → REJECTED`, and returns the participant `ELECTION_SUBMITTED → PENDING_ELECTION`.

Non-responders get default treatment. After the clock has passed the case's `default_treatment_date` — strictly after; applying at or before it is rejected with `ERR_DEFAULT_TREATMENT_WINDOW_NOT_PASSED` (HTTP 409) — a `PlanAdministrator` may apply the default to a participant whose `distribution_status` is `PENDING_ELECTION` or `RESTORED` (otherwise `ERR_ELECTION_INVALID_STATE`) and whose `locate_status` is not `MISSING` (otherwise `ERR_PARTICIPANT_MISSING_REQUIRES_SEARCH`, HTTP 409 — the search protocol must run for missing participants). The case must be `DISTRIBUTION_IN_PROGRESS` (otherwise `ERR_CASE_INVALID_STATE`), and the gates evaluate in §2.9 order: case status and distribution state first, then the default-treatment window, then the missing-participant gate, and the balance-tier rule last — a request that fails both the window and the missing gate reports `ERR_DEFAULT_TREATMENT_WINDOW_NOT_PASSED`. The tier is resolved on `net_distributable_cents` against two statutory limits: below 100000 cents (1000.00 dollars) the payout method is `LUMP_SUM_CHECK`; at or above 100000 and at or below 500000 cents (5000.00 dollars) the method is `AUTO_ROLLOVER_IRA`; above 500000 the request is rejected with `ERR_BALANCE_EXCEEDS_FORCED_LIMIT` (HTTP 422). The boundaries are inclusive-low and inclusive-high: exactly 100000 cents rolls over, exactly 500000 cents rolls over, and 500001 is rejected. The created payout has `source` `DEFAULT_TREATMENT`, the tier-selected method, withholding computed by the same rule as election payouts, and the same blackout-dependent initial status (`PREPARED` during a blackout, else `ISSUED`); the participant moves to `ELECTION_ACCEPTED` as with an accepted election.

The `Recordkeeper` settles payouts. Marking a payout cleared requires it to be `ISSUED` (otherwise `ERR_PAYOUT_NOT_CLEARABLE`, HTTP 409); clearing stamps `cleared_at`, moves the payout `ISSUED → CLEARED`, moves the linked election (if any) `ACCEPTED → SETTLED`, and resolves the participant by method — a `LUMP_SUM_CHECK` payout takes the participant to `PAID_OUT`, while any of the rollover methods (`DIRECT_ROLLOVER_IRA`, `DIRECT_ROLLOVER_QUALIFIED_PLAN`, `AUTO_ROLLOVER_IRA`) takes the participant to `AUTO_ROLLED_OVER`. On the case ledger, `paid_out_cents` increases by the payout's `gross_cents`, `remaining_undistributed_cents` decreases by the same gross, and `resolved_participant_count` is recomputed.

Time, not a user, detects the uncashed check. Every clock advance runs a sweep over all `ISSUED` payouts with method `LUMP_SUM_CHECK` across all cases, in `issued_at` ascending order (ties by `created_at` ascending): a check becomes `STALE_UNCASHED` when the current clock has reached its `issued_at` plus 90 days — the boundary is inclusive, so a check exactly 90 days old is stale. The transition stamps `stale_marked_at`, and its cascade flags the participant `FLAGGED_UNCASHED` (with `flagged_at` stamped) only when the participant's `locate_status` was `UNVERIFIED` — this is the system's half of uncashed-check identification, complementing the `Recordkeeper`'s manual flag.

A stale check is voided by the `Recordkeeper`. Voiding requires the payout to be `STALE_UNCASHED` (otherwise `ERR_PAYOUT_NOT_VOIDABLE`, HTTP 409). The void moves the payout to `VOIDED` with no ledger movement — the uncashed gross never left `remaining_undistributed_cents` in the first place — returns the participant `ELECTION_ACCEPTED → PENDING_ELECTION`, and flips the linked election (if any) `ACCEPTED → SUPERSEDED`, so a fresh election is required to re-resolve the participant.

### 3.7. Termination Expenses, the Determination Letter, and Case Closure

Termination expenses are allocated across participants by a `PlanAdministrator`. Creating an `ExpenseAllocation` carries the case's `termination_case_id`, a `method` of `PRO_RATA_BY_BALANCE` or `EQUAL_PER_CAPITA`, a `total_expense_cents` strictly greater than zero, and a `description` such as the recordkeeper's final invoice. The case must be `TERMINATION_EFFECTIVE`, `DISTRIBUTION_IN_PROGRESS`, or `FINAL_RECONCILIATION` (otherwise `ERR_CASE_INVALID_STATE`); the expense is blocked while any participant of the case is `ELECTION_ACCEPTED`, because payout amounts are already committed (otherwise `ERR_PAYOUTS_ALREADY_COMMITTED`, HTTP 409); and the eligible set must be non-empty (otherwise `ERR_NO_ELIGIBLE_PARTICIPANTS`, HTTP 409).

The eligible set is the case's participants whose `distribution_status` is `PENDING_ELECTION`, `ELECTION_SUBMITTED`, or `RESTORED` at execution time — forfeited and terminally resolved participants are never debited — and its size is frozen at creation as the allocation's `eligible_participant_count`. Rounding order is pinned: each participant's share is rounded first, and the remainder is reconciled second; the implementation must never sum-then-round. Under `PRO_RATA_BY_BALANCE`, each share is the total expense multiplied by the participant's `vested_balance_cents`, divided by the sum of `vested_balance_cents` over the eligible set, rounded half up to whole cents (if that sum is zero, every share is zero and the remainder rule below applies unchanged). Under `EQUAL_PER_CAPITA`, each share is the total expense divided by the number of eligible participants, rounded half up — identical inputs thereby produce different per-participant cents than the pro-rata variant. The remainder, computed as the total expense minus the sum of the rounded shares (it may be positive or negative), is added to the share of the eligible participant with the largest `vested_balance_cents`, ties broken by earliest `created_at`; that participant is recorded at creation as the `remainder_recipient_participant_id`. Each debited participant's `termination_expense_share_cents` increases by their final share and their `net_distributable_cents` is recomputed; the debit touches only computed balance fields, so a debited participant's `version` and `updated_at` are unchanged. Two fiscal guards apply last, in §2.9 order: the total expense may not exceed the case's `remaining_undistributed_cents` (otherwise `ERR_INSUFFICIENT_REMAINING_BALANCE`, HTTP 402), and no computed share may exceed its participant's `vested_balance_cents` (otherwise `ERR_EXPENSE_EXCEEDS_PARTICIPANT_BALANCE`, HTTP 422). On the case ledger, `expense_paid_cents` increases by `total_expense_cents` and `remaining_undistributed_cents` decreases by it.

The IRS determination letter (Form 5310) runs on its own track. Creating a `DeterminationLetterRequest` carries the case's `termination_case_id` and an `intended_filing_date`, and is permitted in any case status except `CLOSED` (otherwise `ERR_CASE_INVALID_STATE`) — but only one open request exists at a time: a create while any request of the case is `DRAFT`, `FILED`, or `ADVERSE` is rejected with `ERR_DLR_ALREADY_OPEN` (HTTP 409). The intended filing date must be covered by a non-superseded `INTERESTED_PARTY` notice whose `action_effective_date` equals it and whose issuance fell in the window from 24 days before the filing date through 10 days before it, inclusive by whole calendar days; an interested-party notice issued outside that window, and a create or file without a live covering notice in it, are rejected with `ERR_INTERESTED_PARTY_WINDOW` (HTTP 422). The new request is `DRAFT`.

Filing the request with the IRS requires it to be `DRAFT` (otherwise `ERR_DLR_INVALID_STATE`, HTTP 409) and re-verifies the interested-party window against the clock: the whole calendar days between the covering notice's `issued_at` and now must be at least 10 and at most 24, inclusive, failing which `ERR_INTERESTED_PARTY_WINDOW`. Filing stamps `filed_at` and moves the request `DRAFT → FILED`. Recording the IRS outcome requires the request to be `FILED` (otherwise `ERR_DLR_INVALID_STATE`) and carries an `outcome` of `FAVORABLE` or `ADVERSE`, moving the request to the matching state. Withdrawal is available from `DRAFT`, `FILED`, or `ADVERSE` (otherwise `ERR_DLR_INVALID_STATE`) and moves the request to `WITHDRAWN`. Note that `ADVERSE` is not terminal: the sponsor must withdraw the adverse request — and may file a fresh one — before the case can close.

Closure is the `IndependentFiduciary`'s final act, and its gates are evaluated as a conjunction: the case must be `FINAL_RECONCILIATION` (otherwise `ERR_CASE_INVALID_STATE`); `all_participants_resolved` must be true (otherwise `ERR_PARTICIPANTS_NOT_ALL_RESOLVED`); no determination letter request may be `DRAFT` or `FILED` (otherwise `ERR_DLR_PENDING_BLOCKS_CLOSE`, HTTP 409); no request may be `ADVERSE` (otherwise `ERR_DLR_ADVERSE_BLOCKS_CLOSE`, HTTP 409 — withdraw first); no blackout period may be `SCHEDULED` or `ACTIVE` (otherwise `ERR_BLACKOUT_TRANSITION_PENDING`); and at least one fiduciary log entry with `entry_type` `CLOSURE_SIGNOFF` must exist for the case (otherwise `ERR_FIDUCIARY_DOC_MISSING`). A successful close moves the case to the terminal `CLOSED`.

### 3.8. The Fiduciary Record

Throughout the lifecycle, both the `PlanAdministrator` and the `IndependentFiduciary` append to the case's fiduciary record. Creating a `FiduciaryLogEntry` carries the case's `termination_case_id`, an `entry_type` of `SEARCH_PROTOCOL_SUMMARY`, `NOTICE_DECISION`, `DISTRIBUTION_DECISION`, `FORFEITURE_RATIONALE`, `PBGC_TRANSFER_RATIONALE`, or `CLOSURE_SIGNOFF`, a free-text `narrative` of at least 50 characters (a shorter narrative is rejected with `ERR_NARRATIVE_TOO_SHORT`, HTTP 422), and an optional `related_entity_id` — a polymorphic reference rather than a strict foreign key, which for a `SEARCH_PROTOCOL_SUMMARY` entry names the `MissingSearchCase` being documented and is the reference the transfer and forfeiture gates look up. The server stamps each entry with the author's `author_user_id` and `author_role` taken from the request headers. An entry may be appended in any case status, including `CLOSED`. The log is append-only: entries carry no `updated_at` and no `version`, and no endpoint modifies or deletes them — the record the independent fiduciary reviews at closure is exactly the record the process produced.

## 4. Endpoint Definitions

All endpoints return the standard envelope of §2.2. Operations that create a new resource return HTTP 201 with the created resource; operations that modify an existing resource or perform a state transition return HTTP 200 with the updated resource. All list endpoints additionally accept the envelope pagination parameters `limit` and `offset`.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the server's logical clock (startup default exactly 2026-08-01T00:00:00Z; non-monotonic moves permitted); runs the stale-check sweep after setting | PlanAdministrator |
| POST | `/termination-cases` | Create a plan termination case (status DRAFT) | PlanAdministrator |
| GET | `/termination-cases/{id}` | Get a termination case including all computed posture and ledger fields | PlanAdministrator, IndependentFiduciary, Recordkeeper, Participant |
| POST | `/termination-cases/{id}/effectuate-termination` | NOTICE_OF_INTENT_ISSUED → TERMINATION_EFFECTIVE at/after the proposed termination date | PlanAdministrator |
| POST | `/termination-cases/{id}/begin-distributions` | TERMINATION_EFFECTIVE → DISTRIBUTION_IN_PROGRESS; requires a live DISTRIBUTION notice and no SCHEDULED/ACTIVE blackout | PlanAdministrator |
| POST | `/termination-cases/{id}/advance-to-reconciliation` | DISTRIBUTION_IN_PROGRESS → FINAL_RECONCILIATION when every participant is resolved | PlanAdministrator |
| POST | `/termination-cases/{id}/reopen-distributions` | FINAL_RECONCILIATION → DISTRIBUTION_IN_PROGRESS when a forfeited participant has been restored | PlanAdministrator |
| POST | `/termination-cases/{id}/close` | FINAL_RECONCILIATION → CLOSED; final fiduciary sign-off | IndependentFiduciary |
| POST | `/participants` | Add a participant to a case census (open until DISTRIBUTION_IN_PROGRESS; vested_pct forced to 100 if already TERMINATION_EFFECTIVE) | PlanAdministrator |
| GET | `/participants/{id}` | Get a participant including computed balances and both state dimensions | PlanAdministrator, IndependentFiduciary, Recordkeeper, Participant |
| GET | `/participants` | List participants with filters (`termination_case_id`, `active_search_case_id`, `locate_status`, `distribution_status`) | PlanAdministrator, IndependentFiduciary, Recordkeeper, Participant |
| POST | `/participants/{id}/contact-flags` | Flag an uncashed check or undeliverable mail | Recordkeeper |
| POST | `/participants/{id}/clear-contact-flag` | Clear a flag (check finally cashed / new address verified) | Recordkeeper |
| POST | `/participants/{id}/declare-missing` | Declare a flagged participant missing; creates or reopens the search case in STEP1_COMMERCIAL_LOCATOR | PlanAdministrator |
| POST | `/participants/{id}/locate` | Mark a MISSING participant located; resolves the open search case and fires the forfeiture-restoration cascade | PlanAdministrator |
| POST | `/participants/{id}/apply-default-treatment` | Apply the balance-tiered default distribution to a non-responder after default_treatment_date | PlanAdministrator |
| GET | `/search-cases/{id}` | Get a search case | PlanAdministrator, IndependentFiduciary, Recordkeeper, Participant |
| GET | `/search-cases` | List search cases with filters (`participant_id`, `termination_case_id`, `status`) | PlanAdministrator, IndependentFiduciary, Recordkeeper, Participant |
| POST | `/search-cases/{id}/attempts` | Record a search attempt; method must match the current step; outcome LOCATED resolves the case and the participant | PlanAdministrator |
| GET | `/search-cases/{id}/attempts` | List attempts of a search case | PlanAdministrator, IndependentFiduciary, Recordkeeper, Participant |
| POST | `/search-cases/{id}/escalate` | Advance the search protocol one step; STEP4 → EXHAUSTED requires the 15-day certified-mail response window to have elapsed | PlanAdministrator |
| POST | `/notices` | Issue a participant notice (NOIT / INTERESTED_PARTY / BLACKOUT_ADVISORY / DISTRIBUTION); supersedes the live notice of the same type; OCC-guarded on the case version | PlanAdministrator |
| GET | `/notices/{id}` | Get a notice | PlanAdministrator, IndependentFiduciary, Recordkeeper, Participant |
| GET | `/notices` | List notices with filters (`termination_case_id`, `notice_type`, `superseded_by_id`) | PlanAdministrator, IndependentFiduciary, Recordkeeper, Participant |
| POST | `/blackout-periods` | Schedule a recordkeeper-transition blackout window (half-open; overlaps rejected, adjacency allowed) | PlanAdministrator |
| GET | `/termination-cases/{id}/blackout-periods` | List blackout periods of a case | PlanAdministrator, IndependentFiduciary, Recordkeeper, Participant |
| POST | `/blackout-periods/{id}/activate` | SCHEDULED → ACTIVE inside the window; requires the covering BLACKOUT_ADVISORY notice | Recordkeeper |
| POST | `/blackout-periods/{id}/complete` | ACTIVE → COMPLETED at/after end_at; releases queued PREPARED payouts | Recordkeeper |
| POST | `/distribution-elections` | Submit a distribution election (self-service or on behalf); supersedes a prior SUBMITTED election; OCC-guarded on the participant version | Participant, PlanAdministrator |
| GET | `/distribution-elections/{id}` | Get an election | PlanAdministrator, IndependentFiduciary, Recordkeeper, Participant |
| GET | `/distribution-elections` | List elections with filters (`participant_id`, `status`) | PlanAdministrator, IndependentFiduciary, Recordkeeper, Participant |
| POST | `/distribution-elections/{id}/accept` | Accept a SUBMITTED election; computes withholding and creates the Payout | PlanAdministrator |
| POST | `/distribution-elections/{id}/reject` | Reject a SUBMITTED election with a reason | PlanAdministrator |
| GET | `/participants/{id}/payouts` | List payouts of a participant | PlanAdministrator, IndependentFiduciary, Recordkeeper, Participant |
| GET | `/distribution-elections/{id}/payouts` | List payouts spawned by an election (0 or 1 element) | PlanAdministrator, IndependentFiduciary, Recordkeeper, Participant |
| POST | `/payouts/{id}/mark-cleared` | Confirm the check was cashed or the rollover accepted by the custodian | Recordkeeper |
| POST | `/payouts/{id}/void` | Void a stale uncashed check; funds never left remaining_undistributed_cents and the participant must be re-resolved | Recordkeeper |
| POST | `/pbgc-transfers` | Submit a missing participant's benefit to the PBGC Missing Participants Program (requires exhausted search, segregation of duties, fiduciary documentation) | IndependentFiduciary |
| GET | `/participants/{id}/pbgc-transfers` | List PBGC transfers of a participant | PlanAdministrator, IndependentFiduciary, Recordkeeper, Participant |
| POST | `/pbgc-transfers/{id}/confirm` | Record PBGC acceptance of the transfer | PlanAdministrator |
| POST | `/pbgc-transfers/{id}/record-rejection` | Record PBGC rejection of the transfer | PlanAdministrator |
| POST | `/forfeitures` | Record a last-resort forfeiture of a missing participant's balance (requires exhausted search, segregation of duties, fiduciary documentation) | IndependentFiduciary |
| GET | `/participants/{id}/forfeitures` | List forfeitures of a participant | PlanAdministrator, IndependentFiduciary, Recordkeeper, Participant |
| POST | `/determination-letter-requests` | Create an IRS determination letter request (Form 5310); requires the covering INTERESTED_PARTY notice | PlanAdministrator |
| GET | `/termination-cases/{id}/determination-letter-requests` | List determination letter requests of a case | PlanAdministrator, IndependentFiduciary, Recordkeeper, Participant |
| POST | `/determination-letter-requests/{id}/file` | File the request with the IRS; the interested-party notice must be 10-24 days old | PlanAdministrator |
| POST | `/determination-letter-requests/{id}/record-determination` | Record the IRS determination outcome | PlanAdministrator |
| POST | `/determination-letter-requests/{id}/withdraw` | Withdraw a request (from DRAFT, FILED, or ADVERSE) | PlanAdministrator |
| POST | `/fiduciary-log-entries` | Append fiduciary documentation (search protocol summary, notice/distribution decisions, forfeiture/PBGC rationale, closure sign-off) | PlanAdministrator, IndependentFiduciary |
| GET | `/termination-cases/{id}/fiduciary-log-entries` | List fiduciary log entries of a case (filter `entry_type`) | PlanAdministrator, IndependentFiduciary, Recordkeeper, Participant |
| POST | `/expense-allocations` | Allocate a termination expense across the eligible participant set with pinned rounding order and remainder assignment | PlanAdministrator |
| GET | `/termination-cases/{id}/expense-allocations` | List expense allocations of a case | PlanAdministrator, IndependentFiduciary, Recordkeeper, Participant |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_PARTICIPANT_OWNERSHIP_VIOLATION | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_NARRATIVE_TOO_SHORT | 422 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_CASE_INVALID_STATE | 409 |
| ERR_CASE_CENSUS_FROZEN | 409 |
| ERR_INVALID_FLAG_TRANSITION | 409 |
| ERR_PARTICIPANT_NOT_FLAGGED | 409 |
| ERR_PARTICIPANT_NOT_MISSING | 409 |
| ERR_SEARCH_CASE_EXHAUSTED_REDECLARE | 409 |
| ERR_SEARCH_CASE_NOT_OPEN | 409 |
| ERR_SEARCH_CASE_NOT_ESCAPABLE | 409 |
| ERR_NO_ATTEMPT_ON_CURRENT_STEP | 409 |
| ERR_SEARCH_METHOD_MISMATCH | 422 |
| ERR_ATTEMPT_TIMESTAMP_INVALID | 422 |
| ERR_CERTIFIED_MAIL_WINDOW_ACTIVE | 409 |
| ERR_CERTIFIED_MAIL_RESPONSE_WINDOW_OPEN | 409 |
| ERR_SEGREGATION_OF_DUTIES_VIOLATION | 403 |
| ERR_FIDUCIARY_DOC_MISSING | 422 |
| ERR_BLACKOUT_WINDOW_OVERLAP | 409 |
| ERR_BLACKOUT_NOT_SCHEDULED | 409 |
| ERR_PBGC_TRANSFER_ALREADY_OPEN | 409 |
| ERR_PBGC_TRANSFER_NOT_SUBMITTED | 409 |
| ERR_FORFEITURE_ALREADY_RECORDED | 409 |
| ERR_DLR_ALREADY_OPEN | 409 |
| ERR_DLR_INVALID_STATE | 409 |
| ERR_PAYOUTS_ALREADY_COMMITTED | 409 |
| ERR_NO_ELIGIBLE_PARTICIPANTS | 409 |
| ERR_ELECTION_INVALID_STATE | 409 |
| ERR_PAYOUT_NOT_CLEARABLE | 409 |
| ERR_PAYOUT_NOT_VOIDABLE | 409 |
| ERR_NOIT_TIMING_WINDOW | 422 |
| ERR_NOIT_DATE_MISMATCH | 422 |
| ERR_INTERESTED_PARTY_WINDOW | 422 |
| ERR_BLACKOUT_NOTICE_WINDOW | 422 |
| ERR_BLACKOUT_NOT_IN_WINDOW | 409 |
| ERR_BLACKOUT_NOT_ENDED | 409 |
| ERR_TERMINATION_DATE_NOT_REACHED | 409 |
| ERR_DEFAULT_TREATMENT_WINDOW_NOT_PASSED | 409 |
| ERR_DISTRIBUTION_NOTICE_REQUIRED | 422 |
| ERR_BLACKOUT_NOTICE_MISSING | 422 |
| ERR_BLACKOUT_TRANSITION_PENDING | 409 |
| ERR_BLACKOUT_ACTIVE_ELECTIONS_BLOCKED | 409 |
| ERR_PARTICIPANT_MISSING_BLOCKS_ELECTION | 409 |
| ERR_PARTICIPANT_MISSING_REQUIRES_SEARCH | 409 |
| ERR_SEARCH_PROTOCOL_INCOMPLETE | 409 |
| ERR_PARTICIPANTS_NOT_ALL_RESOLVED | 409 |
| ERR_DLR_PENDING_BLOCKS_CLOSE | 409 |
| ERR_DLR_ADVERSE_BLOCKS_CLOSE | 409 |
| ERR_NO_REOPENABLE_PARTICIPANT | 409 |
| ERR_BALANCE_EXCEEDS_FORCED_LIMIT | 422 |
| ERR_INSUFFICIENT_REMAINING_BALANCE | 402 |
| ERR_EXPENSE_EXCEEDS_PARTICIPANT_BALANCE | 422 |
| ERR_ZERO_BALANCE_TRANSFER | 422 |
