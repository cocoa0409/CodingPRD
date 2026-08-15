# Neighborhood Pet-Sitting Cooperative API — Product Requirements Document

## 1. Introduction

A neighborhood pet-sitting cooperative runs on reciprocity: members take turns caring for one another's pets, and the currency of that exchange is hours. This document specifies the API that operates such a cooperative — vetting applicants through mutual references, publishing sitting requests, matching them with available sitters, tracking keys and entry events during the sit, and settling hour balances when the work is done. Because the cooperative has no cash economy, the integrity of its hours ledger and the trustworthiness of its members are the product; every rule in this document exists to protect one or the other.

The system must therefore behave like a careful treasurer and a skeptical membership committee at once. It keeps an append-only ledger of hour movements, distinguishes hours that are merely promised from hours that are earned, prices holiday demand without repricing commitments already made, and gives administrators and peer mediators a disciplined path for handling incidents, disputes, and — when necessary — removal of a member. All resources are mounted under the `/coop` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the entire API.

### 2.1. Membership Roles and Caller Identity

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or presenting a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Three roles exist, spelled exactly as follows: `Anonymous`, `CoopAdmin`, and `Member`.

An `Anonymous` caller is an unauthenticated applicant; `X-User-ID` is an opaque identifier not tied to any persisted entity, and the only operation open to this role is submitting a membership application. A `CoopAdmin` is a cooperative administrator; here again `X-User-ID` is an opaque operator identifier not tied to any persisted entity — the server never compares it against any entity's `id`, and administrative authority comes entirely from the role. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting Member; ownership checks on any resource that references a Member — for example a sitting request's `owner_member_id`, a claim's `claimer_member_id`, an assignment's `sitter_member_id`, a reference's `referee_member_id`, or a dispute's `mediator_member_id` — compare that foreign-key field to `X-User-ID`.

Each operation additionally restricts which roles may invoke it (§4). A caller whose role is not permitted for the endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403). Where a role is correct but the operation requires a specific identity — the request owner, the claimer, the sitter, the assigned mediator, or the referee — a caller who is not that party is rejected with `ERR_FORBIDDEN` (HTTP 403).

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

### 2.3. Pagination and List Filtering

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

Several collections support equality filters beyond pagination, each named after the field it matches: the member list filters by `vetting_status`; a member's pet profiles filter by `active`; holiday windows filter by `enabled`; sitting requests filter by `status` and by `owner_member_id`; the claims of a request filter by `status`; entry logs filter by `event_type`; incidents filter by `status`; disputes filter by `status`, `initiator_member_id`, and `respondent_member_id`; and a member's credit ledger filters by `entry_type`.

### 2.4. The Hours Ledger: Single Source of Truth for Credit

Every movement of hours through the cooperative is recorded as an append-only CreditLedgerEntry. Each entry names the affected account via `member_id`, classifies itself with an `entry_type` drawn from `SIT_EARNED`, `SIT_SPENT`, `CANCELLATION_PENALTY`, `INCIDENT_PENALTY`, `MEDIATION_ADJUSTMENT`, and `JOINING_GRANT`, and carries a signed `delta_hours` — positive when hours are credited, negative when they are debited. Entries that arise from a sitting record the assignment's `sitting_assignment_id`; the field is null for entries unrelated to an assignment. Entries of type `MEDIATION_ADJUSTMENT` record the originating dispute in `dispute_id`; for every other entry type that field is null. A human-readable `memo` explains each entry.

A member's `credit_balance_hours` is not stored as an independent fact: it is derived by replaying that member's ledger entries in chronological order — `created_at` ascending, with the entry's `id` ascending as the tiebreaker — and summing `delta_hours`. The balance is updated inline every time an entry is appended. A positive balance means the cooperative owes the member sittings; a negative balance means the member owes sittings. Hours that have been promised but not yet earned are tracked separately as `provisional_credit_hours` and never enter the ledger until settlement.

### 2.5. Reliability Standing

Trust in the cooperative is quantified as each member's `reliability_score`, an integer that begins at 50 when the membership application is created and can never leave the range 0 to 100 — adjustments that would cross either boundary are clamped. The score moves event by event rather than being recomputed: settling a completed sit adds 2 points to the sitter; a sitter cancelling less than 24 hours before the scheduled start costs 8 points; being found at fault for an incident costs 15 points; an access handoff reported lost costs the sitter 10 points; and a dispute escalated to the removal track costs the respondent 25 points. Claiming a sitting request requires a score of at least 30.

### 2.6. Logical Time and Time-Driven Cascades

The server keeps a logical clock rather than consulting wall-clock time. Before any call to set it, the clock reads exactly 2026-08-01T00:00:00Z and must not fall back to wall-clock time. A `CoopAdmin`-only capability advances this clock to a supplied `to_iso8601` instant and returns the resulting logical time as `current_utc`; advancing the clock triggers the time-based cascades described in §3, such as the expiry of unclaimed sitting requests. All timestamps in the system are ISO 8601 UTC. Wherever this document speaks of a time interval belonging to a request, an assignment, or a holiday window, the interval is half-open: it includes its start instant and excludes its end instant.

### 2.7. Request Evaluation Order

When several checks could reject the same request, the server evaluates them in a fixed pipeline so that the surfaced error is deterministic. The order is:

1. Presence and well-formedness of `X-User-ID` and `X-User-Role` — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. Role permission for the endpoint — otherwise `ERR_UNAUTHORIZED` (HTTP 403).
3. Existence of every resource named in the path, resolved left to right — otherwise `ERR_NOT_FOUND` (HTTP 404).
4. Staleness: any expected-version field in the payload must match the parent entity's current `version` — otherwise `ERR_STALE_VERSION` (HTTP 412).
5. State: the target resource must be in the state its transition requires — otherwise `ERR_INVALID_STATE` (HTTP 409).
6. Identity and ownership: the caller must be the specific party the operation names — otherwise `ERR_FORBIDDEN` (HTTP 403).
7. Vetting standing: counterparties that must be vetted members are checked — otherwise `ERR_MEMBER_NOT_VETTED` (HTTP 409).
8. Reliability floor for claiming — otherwise `ERR_RELIABILITY_TOO_LOW` (HTTP 409).
9. Reference integrity and reciprocity — otherwise `ERR_RECIPROCITY_NOT_MET` (HTTP 409).
10. Sitter scheduling overlap — otherwise `ERR_SITTER_OVERLAP` (HTTP 409).
11. Handoff earliness — otherwise `ERR_HANDOFF_TOO_EARLY` (HTTP 409).
12. Handoff completion before work begins — otherwise `ERR_ACCESS_NOT_HANDED_OFF` (HTTP 409).
13. Entry-log time-window conformance — otherwise `ERR_ENTRY_OUT_OF_WINDOW` (HTTP 422).
14. Owner credit sufficiency at posting — otherwise `ERR_INSUFFICIENT_CREDIT` (HTTP 402).
15. Pet-profile validity at posting — otherwise `ERR_PET_PROFILE_INVALID` (HTTP 409).
16. Self-dealing prohibitions — otherwise `ERR_SELF_REFERENCE` (HTTP 422).
17. Basic field validation of the request payload — otherwise `ERR_INVALID_REQUEST` (HTTP 400).
18. Settlement freedom from open incidents — otherwise `ERR_UNRESOLVED_INCIDENT` (HTTP 409).
19. Removal eligibility — otherwise `ERR_REMOVAL_CRITERIA_NOT_MET` (HTTP 409).

Earlier steps mask later ones: a request failing step 3 never reports a step-5 violation, and so on.

### 2.8. Nested Resource Resolution

Endpoints that address a resource through its parents — for example a claim addressed through its sitting request — validate path identifiers strictly left to right. The identifier sequence used across the API is `{memberId}`, `{referenceId}`, `{petProfileId}`, `{windowId}`, `{requestId}`, `{claimId}`, `{assignmentId}`, `{handoffId}`, `{incidentId}`, and `{disputeId}`. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource; identifiers to the right of that point are never examined.

### 2.9. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp records creation as ISO 8601 UTC with three fractional digits, and `updated_at` records the most recent modification in the same format, refreshing on any change. The `version` is an integer that starts low and increments on every mutation of the resource. Two record types are deliberately leaner: an EntryLog and a CreditLedgerEntry each carry only `id` and `created_at` — both `updated_at` and `version` are absent, because both records are immutable once appended.

### 2.10. Hour Arithmetic and Rounding

All hour amounts in the system — offers, settlements, penalties, grants, and balances — are decimal values rounded half-up to exactly 2 decimal places, and all internal arithmetic on hours is performed in decimal to avoid floating-point drift. Hour values are represented in API payloads as numbers, not strings. The `reliability_score`, by contrast, is always an integer. Time-interval comparisons are made at second precision in UTC.

### 2.11. Optimistic Concurrency on Claim Acceptance

Exactly one operation in the API takes a version field: accepting a claim against a sitting request. The acceptance payload must carry `expected_sitting_request_version`, holding the request's `version` as the owner last observed it. If another writer has advanced the request's version since that observation — for example by accepting a different claim, which legitimately moves the request out of `OPEN`, or by cancelling it — the acceptance is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the owner from acting on a request they have not re-read. No other endpoint accepts a version field.

## 3. Business Logic & Workflows

### 3.1. Joining the Cooperative: Application, Vouching, and Vetting

Membership begins with an application open to anyone. The applicant supplies a `display_name` (their full legal name), an `email` that must be unique across the cooperative compared case-insensitively, an `address_block` identifying their neighborhood block (for example `MAPLE-100`) for the residency check, and a `phone` number capable of receiving SMS for emergency contact. An optional `mediator_flag` — defaulting to false — marks the applicant as willing to mediate disputes later. A new application lands with `vetting_status` set to `APPLIED`, a `reliability_score` of 50, and both `credit_balance_hours` and `provisional_credit_hours` at zero.

Vetting rests on mutual vouching. The applicant — or an administrator acting on their behalf — registers references, each naming a `referee_member_id` for an existing vetted member who vouches for the applicant recorded as `subject_member_id`, a `relationship_years` count that must be at least 1, and an `attestation_text` of at least 20 characters. Self-vouching is prohibited: a reference whose referee equals its subject is rejected with `ERR_SELF_REFERENCE`. Each reference begins in `PENDING` status. The referee may withdraw their own still-`PENDING` reference, moving it to `WITHDRAWN`; the caller's identity must equal the reference's `referee_member_id` or the withdrawal is rejected with `ERR_FORBIDDEN`. An administrator accepts or rejects a pending reference; acceptance additionally requires the referee to be `VETTED` (otherwise `ERR_REFEREE_NOT_VETTED`) and again rejects a self-pairing with `ERR_SELF_REFERENCE`. Either decision stamps `decided_at`. Reciprocity is tracked automatically: when a reference is accepted and the reverse reference — the one in which the subject vouches for the referee — is also `ACCEPTED`, the system links the pair by setting `reciprocal_reference_id` on both rows.

Once at least two references for the applicant exist in `PENDING`, an administrator advances the applicant from `APPLIED` to `REFERENCES_PENDING`; with fewer than two the attempt fails with `ERR_INSUFFICIENT_REFERENCES`. Before vetting can be finalized, the applicant must personally accept the cooperative liability agreement, which stamps `accepted_liability_at`. Finalization moves the member from `REFERENCES_PENDING` to `VETTED` and enforces three gates: at least two `ACCEPTED` references (otherwise `ERR_INSUFFICIENT_REFERENCES`), reciprocity — for every accepted reference, the reverse reference must also be `ACCEPTED` (otherwise `ERR_RECIPROCITY_NOT_MET`) — and a non-null `accepted_liability_at` (otherwise `ERR_LIABILITY_NOT_ACCEPTED`). On finalization the system stamps `co_op_joined_at`, grants the new member 10.0 hours by setting `credit_balance_hours` to 10.0, and appends a `JOINING_GRANT` ledger entry for +10.0 hours.

Standing can be lost and, in one case, regained. An administrator may suspend a `VETTED` member, supplying a non-empty `suspension_reason` (an empty reason fails with `ERR_INVALID_REQUEST`). Suspension cascades immediately: every `OPEN` sitting request the member owns is `CANCELLED` with its `cancelled_reason` recorded as `OWNER_SUSPENDED`; every `PENDING` claim the member has made moves to `WITHDRAWN`; and every `CONFIRMED` assignment touching the member is cancelled — `CANCELLED_BY_SITTER` when the member was the sitter, `CANCELLED_BY_OWNER` when they were the owner — with the sitter's `provisional_credit_hours` reversed in each case. Reinstating a `SUSPENDED` member returns them to `VETTED` and clears `suspension_reason` to null.

Removal is permanent and gated. An administrator may remove a member who is `VETTED` or `SUSPENDED` only when one of two eligibility paths holds: the member is the respondent on a dispute that has reached `ESCALATED_REMOVAL`, or the member has accumulated at least 2 incidents resolved `RESOLVED_AT_FAULT` within the trailing 365 days — an incident dated exactly 365 days ago still counts. Failing both paths rejects the removal with `ERR_REMOVAL_CRITERIA_NOT_MET`. Removal records the supplied `removal_reason`, zeroes both `credit_balance_hours` and `provisional_credit_hours` — appending a `MEDIATION_ADJUSTMENT` ledger entry equal to the negated pre-removal balance when that balance was non-zero — deactivates every pet profile the member owns, cancels all non-terminal sitting requests, and cancels all non-terminal assignments with provisional reversal. `REMOVED` is terminal; a removed member can never be reinstated.

### 3.2. Pet Profiles and the Care Baseline

Before a member can ask the cooperative for a sit, the pet must be documented. A member creates a pet profile with the pet's `pet_name`, its `species` — one of `DOG`, `CAT`, `BIRD`, `RABBIT`, or `OTHER` — free-text `routine_notes` covering feeding and walking, `medical_notes` covering medications, conditions, and allergies, and emergency-veterinarian details: `emergency_vet_name`, `emergency_vet_phone`, and `emergency_vet_address`. The profile also records whether the owner has explicitly accepted the pet-care liability waiver via `liability_waiver_accepted`; no sitting request may be posted for a pet whose waiver is not accepted. The creating member becomes the profile's `owner_member_id`, and the profile starts with `active` set to true.

Profiles are soft-deleted. Deactivating a profile — permitted only to its owner, with anyone else rejected as `ERR_FORBIDDEN` — sets `active` to false, which hides the pet from new requests while preserving its history. The pet-profile listing can be filtered by `active`.

### 3.3. Holiday Demand and Posting a Sitting Request

Demand in the cooperative is seasonal, and pricing acknowledges it. An administrator defines a holiday window with a `name` (for example "Thanksgiving 2026"), an inclusive `window_start`, an exclusive `window_end`, and a `demand_multiplier` between 1.0 and 3.0; the `enabled` flag defaults to true. Disabling a window simply sets `enabled` to false and never reprices offers that were already computed — once an offer is locked at posting it stays locked.

A member posts a sitting request by naming the `pet_profile_id` of the pet to be sat, the `start_at` and `end_at` instants, and visit-specific `instructions`. The posting member becomes the request's `owner_member_id`. Basic validation runs first: `start_at` must lie in the future, `end_at` must be after `start_at`, and the duration must be at least 1 hour and at most 72 hours; violations are rejected with `ERR_INVALID_REQUEST`. The named pet profile must be active, must belong to the caller, and must carry an accepted liability waiver, or posting fails with `ERR_PET_PROFILE_INVALID`.

The offered price of the sit, `credit_hours_offered`, is computed once at posting. The duration is measured in fractional hours. The system then considers every enabled holiday window whose interval intersects the requested interval — meaning the window starts before the request ends and ends after the request starts — and takes the single highest `demand_multiplier` among them; multipliers never compound, and when no enabled window intersects, the multiplier is 1.0. The offer is the duration multiplied by that multiplier, rounded half-up to 2 decimal places. Because the owner is spending hours, posting also requires the owner's credit to stretch far enough: the balance after subtracting the offer must not fall below a 5.0-hour overdraft floor — otherwise the posting is rejected with `ERR_INSUFFICIENT_CREDIT` (HTTP 402).

A fresh request is `OPEN` and perishable: its `expires_at` is set to four hours before `start_at`, and when the logical clock reaches that moment with no accepted claim, the request moves to `EXPIRED` on its own. The request listing can be filtered by `status` and by `owner_member_id`.

### 3.4. Claiming and Assignment Formation

A vetted member who wants the sit claims an `OPEN` request with a short `message` pitch. The caller is recorded as `claimer_member_id`, the claim starts `PENDING`, and the sitting request is linked through `sitting_request_id`. Self-dealing is barred at this door: the claimer must not be the request's owner (`ERR_SELF_REFERENCE`), and a claimant whose `reliability_score` is below 30 is turned away with `ERR_RELIABILITY_TOO_LOW`. A claimer may withdraw their own pending claim — the caller must be the claimer, otherwise `ERR_FORBIDDEN` — moving it to `WITHDRAWN`, and the owner may reject a pending claim, which stamps `decided_at` and moves it to `REJECTED`. The claims listing for a request can be filtered by `status`.

Acceptance is the pivotal transaction of the marketplace, and its checks run in the pipeline order of §2.7 — authentication, role, path existence, staleness, state, ownership, then business rules. The caller must be the request's owner (`ERR_FORBIDDEN`); the request must still be `OPEN` and the claim still `PENDING` (either violation surfaces as `ERR_INVALID_STATE`); the claimant must currently be `VETTED` (`ERR_MEMBER_NOT_VETTED`); the claimant's reliability is verified again at no less than 30 (`ERR_RELIABILITY_TOO_LOW`); and the claimant must have no other assignment in `CONFIRMED` or `IN_PROGRESS` whose scheduled interval overlaps the request's interval (`ERR_SITTER_OVERLAP`). Overlap is judged on half-open intervals, so two sits where one ends exactly when the other begins do not conflict. Finally, the payload's `expected_sitting_request_version` must equal the request's current `version`, per §2.11; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

When acceptance succeeds, a cascade fires in one motion. The claim becomes `ACCEPTED` with `decided_at` stamped; the request moves `OPEN` → `CLAIMED` → `ASSIGNED` and its `version` increments; every other `PENDING` claim on the request is `REJECTED`; a new assignment is persisted in `CONFIRMED` with `scheduled_start_at` and `scheduled_end_at` copied from the request, the owner denormalized onto `owner_member_id`, and the sitter taken from the accepted claim as `sitter_member_id`; an access handoff is created in `PENDING`; and the sitter's `provisional_credit_hours` increases by the request's `credit_hours_offered` — the provisional variant of the settlement credit, an optimistic posting that settlement may later reduce.

Either side can still walk away before work begins. Cancelling a request in `OPEN` or `CLAIMED` is the owner's prerogative alone (`ERR_FORBIDDEN`); all `PENDING` claims are `REJECTED`, and if an accepted claim already existed its assignment becomes `CANCELLED_BY_OWNER` with the provisional hours reversed. Once the request is `ASSIGNED`, either the owner or the sitter may cancel, recording the supplied `cancelled_reason`; the assignment becomes `CANCELLED_BY_OWNER` or `CANCELLED_BY_SITTER` accordingly and the provisional hours are reversed. A sitter who cancels late pays for it: when fewer than 24 hours remain before `scheduled_start_at` — exactly 24 hours out is not late — the sitter's balance is debited a penalty equal to the request's `credit_hours_offered` multiplied by 0.25, rounded half-up to 2 decimal places, posted as a `CANCELLATION_PENALTY` ledger entry, and the sitter's `reliability_score` drops by 8.

### 3.5. Keys, Access, and the Entry Log

A sit cannot start until the sitter can get in. While the handoff created at acceptance is still `PENDING`, the owner records the practical details on it: the `handoff_method` — one of `IN_PERSON`, `LOCKBOX`, `CONCIERGE`, or `SMART_LOCK` — and the `access_code_ciphertext`, the encrypted access code. That ciphertext is revealed to the sitter only once the assignment is `CONFIRMED` and the current time is within the two hours preceding `scheduled_start_at`. When the keys physically change hands, the owner confirms the handoff; confirmation earlier than two hours before the scheduled start is rejected with `ERR_HANDOFF_TOO_EARLY`, and success stamps `handed_off_at` and moves the handoff to `HANDED_OFF`. After the sit, the owner confirms the return of keys — allowed only when the assignment has reached `COMPLETED_PENDING_REVIEW`, `SETTLED`, `CANCELLED_BY_OWNER`, or `CANCELLED_BY_SITTER` (otherwise `ERR_INVALID_STATE`) — stamping `returned_at` and moving the handoff to `RETURNED`. If the credentials go missing, either the owner or the sitter reports the handoff lost; the handoff moves to `LOST`, the system automatically files an incident with `severity` `MAJOR` and the description "Access credentials lost", and the sitter's `reliability_score` drops by 10.

During the sit itself, members append entry logs to the assignment: an `event_type` of `CHECK_IN`, `CHECK_OUT`, `INCIDENT_NOTE`, `PET_FED`, `MEDICATION_GIVEN`, or `VET_VISIT`; an `occurred_at` timestamp; and optional `notes` — which become required when the event is an `INCIDENT_NOTE` or a `MEDICATION_GIVEN`. The caller is recorded as `actor_member_id`. Entries are only accepted within the sit's plausible window, from 30 minutes before `scheduled_start_at` through 4 hours after `scheduled_end_at`, inclusive at both ends; anything outside is rejected with `ERR_ENTRY_OUT_OF_WINDOW` (HTTP 422).

The first `CHECK_IN` is load-bearing. If the assignment is still `CONFIRMED`, that check-in moves the assignment to `IN_PROGRESS` and the request to `IN_PROGRESS`, and stamps the assignment's `actual_start_at` with the entry's `occurred_at`. But no work may begin without keys: a check-in attempted while the handoff is not yet `HANDED_OFF` is rejected with `ERR_ACCESS_NOT_HANDED_OFF`. Entry logs are an audit trail — immutable once written, filterable by `event_type`, and carrying only `id` and `created_at` as system fields.

### 3.6. Completion, Settlement, and the Exchange Ledger

When the work is done, the sitter checks out. Checkout requires the caller to be the sitter (`ERR_FORBIDDEN`), the assignment to be `IN_PROGRESS` (`ERR_INVALID_STATE`), and at least one prior `CHECK_IN` entry (otherwise `ERR_NO_CHECKIN`). Checkout stamps `actual_end_at` with the current time, appends a `CHECK_OUT` entry log, moves the assignment to `COMPLETED_PENDING_REVIEW`, and moves the request to `COMPLETED`.

Settlement is an administrative act that turns provisional promises into ledger facts. An administrator settles an assignment in `COMPLETED_PENDING_REVIEW` (`ERR_INVALID_STATE` otherwise), but only while no incident on that assignment remains `FILED` or `UNDER_REVIEW` — an open incident blocks settlement with `ERR_UNRESOLVED_INCIDENT`. The final settlement variant compares promise to reality: the scheduled duration and the actual duration — `scheduled_start_at` to `scheduled_end_at`, and `actual_start_at` to `actual_end_at` — are each measured in hours; the shortfall is the scheduled hours minus the actual hours, never below zero; and if that shortfall is strictly more than 25 percent of the scheduled duration, the sitter departed early enough to reprice, so the base becomes the actual hours multiplied by the demand multiplier locked at posting and then multiplied by 0.5. When the shortfall is 25 percent or less, no repricing occurs and the base is the request's full `credit_hours_offered`. Either way the result, rounded half-up to 2 decimal places, is recorded as `credit_hours_settled`.

The cascade then settles accounts: the sitter's `credit_balance_hours` increases by `credit_hours_settled` with a `SIT_EARNED` entry, the owner's `credit_balance_hours` decreases by the same amount with a `SIT_SPENT` entry, the sitter's `provisional_credit_hours` is reduced by the request's `credit_hours_offered`, and the sitter's `reliability_score` gains 2 points, capped at 100. Note the deliberate divergence between the two variants: the provisional posting at acceptance is always the full offer, while the final settlement may be smaller when the sitter left early. Members and administrators can inspect the full ledger for a member, filtered by `entry_type` if desired; the balance reported on the member is always the chronological replay described in §2.4.

### 3.7. Incidents, Disputes, and Removal from the Cooperative

When something goes wrong during a sit, a member files an incident on the assignment, giving a `severity` of `MINOR`, `MAJOR`, or `EMERGENCY`, a `description` of at least 30 characters, and a `vet_involved` flag recording whether the emergency veterinarian was contacted. The caller is recorded as `reporter_member_id` and the incident begins `FILED`. An administrator takes it under review, moving it `FILED` → `UNDER_REVIEW`, and may dismiss an incident from either of those states, ending it as `DISMISSED`.

Resolution comes in two flavors. Resolving with `outcome` set to `AT_FAULT` requires the payload to name an `at_fault_member_id` (omitting it fails with `ERR_INVALID_REQUEST`) and ends the incident as `RESOLVED_AT_FAULT`: the at-fault member's `reliability_score` drops by 15, and if the assignment was already `SETTLED`, an `INCIDENT_PENALTY` entry debits that member half of the assignment's `credit_hours_settled`, rounded half-up to 2 decimal places. A member who reaches at least 2 at-fault resolutions within the trailing 365 days thereby becomes eligible for removal under §3.1. Resolving with `outcome` set to `NO_FAULT` ends the incident as `RESOLVED_NO_FAULT` with no further effects. The incident listing can be filtered by `status`.

Grievances broader than a single incident go through disputes. A member opens a dispute naming the `respondent_member_id`, a `dispute_type` of `SITTING_QUALITY`, `CREDIT_BALANCE`, `ACCESS_DAMAGE`, or `BEHAVIOR`, and a `statement` of at least 40 characters; a `sitting_assignment_id` may supply context and is required when the type is `SITTING_QUALITY`. The caller becomes `initiator_member_id` and the dispute begins `FILED`. When the dispute references an assignment that is sitting in `COMPLETED_PENDING_REVIEW`, that assignment moves to `DISPUTED` and its settlement is blocked until the dispute resolves. An administrator then assigns a mediator, moving the dispute to `MEDIATION`; the proposed `mediator_member_id` must belong to a `VETTED` member whose `mediator_flag` is true (otherwise `ERR_MEDIATOR_INVALID`) and must be neither the initiator nor the respondent (otherwise `ERR_MEDIATOR_CONFLICT`).

From `MEDIATION`, the assigned mediator — and only the mediator, verified by identity (`ERR_FORBIDDEN`) — steers the dispute to one of three endings. Resolving with `outcome` `UPHELD` requires `resolution_notes` (`ERR_INVALID_REQUEST` if absent) and ends the dispute as `RESOLVED_UPHELD`; resolving with `outcome` `DISMISSED` ends it as `RESOLVED_DISMISSED`. For a `CREDIT_BALANCE` dispute, the mediator may include a non-zero `credit_adjustment_hours`, which posts a `MEDIATION_ADJUSTMENT` entry crediting the initiator by that amount and a matching entry debiting the respondent by the same amount. In either resolution, when the dispute references an assignment currently `DISPUTED`, the assignment settles — running the same settlement cascade as §3.6, from the final-variant computation through the reliability bonus. The third ending is escalation, permitted only for `ACCESS_DAMAGE` and `BEHAVIOR` disputes (anything else fails with `ERR_INVALID_REQUEST`): the mediator supplies `resolution_notes`, the dispute becomes `ESCALATED_REMOVAL`, the respondent's `reliability_score` drops by 25, and the respondent becomes eligible for administrative removal. The dispute listing can be filtered by `status`, `initiator_member_id`, and `respondent_member_id`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that read or modify an existing resource return `200 OK`. The table below summarizes the HTTP contract only — request payloads, response bodies, and side effects are defined by the workflows in §3 and the principles in §2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/coop/_clock/set_current_utc` | Set the server's logical clock | CoopAdmin |
| POST | `/coop/members` | Apply for co-op membership | Anonymous |
| GET | `/coop/members` | List members | CoopAdmin, Member |
| GET | `/coop/members/{memberId}` | Get member by id | CoopAdmin, Member |
| POST | `/coop/members/{memberId}/accept-liability` | Member accepts the co-op liability agreement | Member |
| POST | `/coop/members/{memberId}/submit-references` | Move an APPLIED member to REFERENCES_PENDING | CoopAdmin |
| POST | `/coop/members/{memberId}/finalize-vetting` | Vet a member after reciprocity and liability checks | CoopAdmin |
| POST | `/coop/members/{memberId}/suspend` | Suspend a member, cascade-cancelling active work | CoopAdmin |
| POST | `/coop/members/{memberId}/reinstate` | Reinstate a suspended member | CoopAdmin |
| POST | `/coop/members/{memberId}/remove` | Permanently remove a member (eligibility-checked) | CoopAdmin |
| POST | `/coop/members/{memberId}/references` | Add a reference for an applicant | CoopAdmin, Member |
| GET | `/coop/members/{memberId}/references` | List references for a subject member | CoopAdmin, Member |
| GET | `/coop/member-references/{referenceId}` | Get a reference by id | CoopAdmin, Member |
| POST | `/coop/member-references/{referenceId}/accept` | Accept a reference | CoopAdmin |
| POST | `/coop/member-references/{referenceId}/reject` | Reject a reference | CoopAdmin |
| POST | `/coop/member-references/{referenceId}/withdraw` | Referee withdraws their own reference | Member |
| POST | `/coop/members/{memberId}/pet-profiles` | Create a pet profile | Member |
| GET | `/coop/members/{memberId}/pet-profiles` | List a member's pet profiles | CoopAdmin, Member |
| GET | `/coop/pet-profiles/{petProfileId}` | Get a pet profile | CoopAdmin, Member |
| POST | `/coop/pet-profiles/{petProfileId}/deactivate` | Soft-delete a pet profile | Member |
| POST | `/coop/holiday-windows` | Create a holiday demand window | CoopAdmin |
| GET | `/coop/holiday-windows` | List holiday windows | CoopAdmin, Member |
| GET | `/coop/holiday-windows/{windowId}` | Get a holiday window | CoopAdmin, Member |
| POST | `/coop/holiday-windows/{windowId}/disable` | Disable a holiday window | CoopAdmin |
| POST | `/coop/sitting-requests` | Post a sitting request | Member |
| GET | `/coop/sitting-requests` | List sitting requests | CoopAdmin, Member |
| GET | `/coop/sitting-requests/{requestId}` | Get a sitting request | CoopAdmin, Member |
| POST | `/coop/sitting-requests/{requestId}/cancel` | Owner or sitter cancels a request/assignment | Member |
| POST | `/coop/sitting-requests/{requestId}/claims` | Claim an OPEN request | Member |
| GET | `/coop/sitting-requests/{requestId}/claims` | List claims for a request | CoopAdmin, Member |
| GET | `/coop/sitting-claims/{claimId}` | Get a claim by id | CoopAdmin, Member |
| POST | `/coop/sitting-requests/{requestId}/claims/{claimId}/accept` | Accept a claim (OCC-guarded) | Member |
| POST | `/coop/sitting-requests/{requestId}/claims/{claimId}/reject` | Reject a claim | Member |
| POST | `/coop/sitting-requests/{requestId}/claims/{claimId}/withdraw` | Claimer withdraws own claim | Member |
| GET | `/coop/sitting-assignments/{assignmentId}` | Get an assignment | CoopAdmin, Member |
| GET | `/coop/sitting-requests/{requestId}/assignment` | Get the assignment for a request (0 or 1 element array) | CoopAdmin, Member |
| POST | `/coop/sitting-assignments/{assignmentId}/checkout` | Sitter checks out, final CHECK_OUT | Member |
| POST | `/coop/sitting-assignments/{assignmentId}/settle` | Settle a completed assignment (posts ledger entries) | CoopAdmin |
| GET | `/coop/sitting-assignments/{assignmentId}/access-handoff` | Get the handoff for an assignment (0 or 1 element array) | CoopAdmin, Member |
| POST | `/coop/access-handoffs/{handoffId}/confirm-handoff` | Owner confirms keys handed to sitter | Member |
| POST | `/coop/access-handoffs/{handoffId}/confirm-return` | Owner confirms keys returned | Member |
| POST | `/coop/access-handoffs/{handoffId}/report-lost` | Owner or sitter reports access lost | Member |
| PUT | `/coop/access-handoffs/{handoffId}` | Owner sets access code / handoff method (only while PENDING) | Member |
| POST | `/coop/sitting-assignments/{assignmentId}/entry-logs` | Append an entry log | Member |
| GET | `/coop/sitting-assignments/{assignmentId}/entry-logs` | List entry logs for an assignment | CoopAdmin, Member |
| POST | `/coop/sitting-assignments/{assignmentId}/incidents` | File an incident on an assignment | Member |
| GET | `/coop/sitting-assignments/{assignmentId}/incidents` | List incidents on an assignment | CoopAdmin, Member |
| GET | `/coop/incidents/{incidentId}` | Get an incident | CoopAdmin, Member |
| POST | `/coop/incidents/{incidentId}/begin-review` | Begin incident review | CoopAdmin |
| POST | `/coop/incidents/{incidentId}/resolve` | Resolve an incident (AT_FAULT or NO_FAULT) | CoopAdmin |
| POST | `/coop/incidents/{incidentId}/dismiss` | Dismiss an incident | CoopAdmin |
| POST | `/coop/disputes` | Open a dispute | Member |
| GET | `/coop/disputes` | List disputes | CoopAdmin, Member |
| GET | `/coop/disputes/{disputeId}` | Get a dispute | CoopAdmin, Member |
| POST | `/coop/disputes/{disputeId}/assign-mediator` | Assign a mediator | CoopAdmin |
| POST | `/coop/disputes/{disputeId}/resolve` | Mediator resolves the dispute | Member |
| POST | `/coop/disputes/{disputeId}/escalate` | Mediator escalates to the removal track | Member |
| GET | `/coop/members/{memberId}/credit-ledger` | List credit ledger entries for a member | CoopAdmin, Member |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3 where the corresponding rule lives.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INSUFFICIENT_REFERENCES` | 409 Conflict |
| `ERR_RECIPROCITY_NOT_MET` | 409 Conflict |
| `ERR_REFEREE_NOT_VETTED` | 409 Conflict |
| `ERR_SELF_REFERENCE` | 422 Unprocessable Entity |
| `ERR_LIABILITY_NOT_ACCEPTED` | 409 Conflict |
| `ERR_MEMBER_NOT_VETTED` | 409 Conflict |
| `ERR_MEDIATOR_INVALID` | 409 Conflict |
| `ERR_MEDIATOR_CONFLICT` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PET_PROFILE_INVALID` | 409 Conflict |
| `ERR_INSUFFICIENT_CREDIT` | 402 Payment Required |
| `ERR_RELIABILITY_TOO_LOW` | 409 Conflict |
| `ERR_SITTER_OVERLAP` | 409 Conflict |
| `ERR_ACCESS_NOT_HANDED_OFF` | 409 Conflict |
| `ERR_HANDOFF_TOO_EARLY` | 409 Conflict |
| `ERR_ENTRY_OUT_OF_WINDOW` | 422 Unprocessable Entity |
| `ERR_NO_CHECKIN` | 409 Conflict |
| `ERR_UNRESOLVED_INCIDENT` | 409 Conflict |
| `ERR_REMOVAL_CRITERIA_NOT_MET` | 409 Conflict |
