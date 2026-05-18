# HOA Community Management API — Product Requirements Document

## 1. Introduction

A homeowners' association is, in the end, a tightly bound community of duties. Owners pay assessments to keep the common areas running; the board collects those funds, polices the bylaws, decides which architectural changes are tolerable, escalates delinquency into recorded liens when payment fails, and convenes elections so the seats around the table refresh on a predictable cadence. Each of those workflows touches the same ledger: a charge that goes overdue feeds the late-fee accrual, the cumulative arrears shape lien eligibility, lien eligibility weaponises the architectural review against owners who fall behind, and the reserve study posture can pause discretionary improvements community-wide. The HOA Community Management API exists to make these intertwined cycles auditable, deterministic, and resistant to off-hours mistakes.

This document specifies the API as a multi-party negotiation system with strong compliance posture. Five roles share the surface — a homeowner role (`Member`) and four board roles (`SecretaryRole`, `TreasurerRole`, `PresidentRole`, `DirectorRole`) — and almost every consequential action requires a recorded board resolution, a clock-anchored cooling-off, or both. Time is explicit: an admin-only endpoint advances a logical clock, which in turn drives lazy evaluation of late fees, auto-fines, silent ACC decisions, election transitions, and lien aging. Money is in integer cents throughout; rounding rules are pinned so that totals reconcile across allocation, accrual, and write-off paths. Reads are paginated with stable ordering; mutations support optimistic concurrency.

The API is mounted under the prefix `/hoa`. All references to endpoints in §3 use business-narrative phrasing; the literal HTTP method and path table appears in §4.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request MUST carry two authentication headers: `X-User-ID` identifying the acting principal, and `X-User-Role` naming the role under which they act. The role value MUST be one of the five strings: `Member`, `SecretaryRole`, `TreasurerRole`, `PresidentRole`, or `DirectorRole`. Requests missing either header, carrying a malformed value, or naming a role outside this enumeration are rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is well-formed but not permitted to invoke the requested endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

All five roles are entity-backed by `Member`. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` (for example a payment's `member_id`, an ACC request's `submitted_by_member_id`, a violation's `opened_by_member_id`, a ballot's `voter_member_id`) compare the resource's foreign-key field to `X-User-ID`. The same identity rule applies to `SecretaryRole`, `TreasurerRole`, `PresidentRole`, and `DirectorRole`: `X-User-ID` is the `id` of the `Member` who currently holds that board seat (verified against `Member.board_role`). A request carrying a board role whose acting member does not in fact hold that seat — or no longer holds it after a certification — is treated as forbidden.

The detailed per-endpoint role matrix is encoded in the §4 endpoint table. Role exclusivity follows segregation-of-duties: the `TreasurerRole` is the sole controller of assessment cycles, write-offs, reserve studies, and reserve-study adoption; the `SecretaryRole` is the sole intake point for architectural review, the sole creator of violations and lien notices (with `PresidentRole` co-authorised on violations only), and the sole certifier of elections; the `PresidentRole` is the sole creator of `Unit`, `Member`, and election records, the sole recorder/releaser of liens, and the sole driver of the logical clock; the `DirectorRole` casts board and ACC votes but holds no exclusive operations.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, has a minimum of 1, and a maximum of 100; values outside that closed interval are rejected. `offset` defaults to 0 and has no upper cap aside from the natural bound of the result set. Results are always sorted by `created_at` in ascending order so that pagination is stable across requests. The `meta` block on every list response carries `limit`, `offset`, `total_count` (the unfiltered server-side count after any query-string filters such as `unit_id` or `status` are applied), and the boolean `has_more` indicating whether further pages exist beyond the current window.

### 2.4. Common Resource Properties, Identifiers, and the Logical Clock

Resources fall into two shapes. Most entities — `Unit`, `Member`, `AssessmentCharge`, `ACCRequest`, `Violation`, `BoardResolution`, `ElectionCycle`, `Lien`, and `ReserveStudy` — carry the common audit triplet `id`, `created_at`, `updated_at`, plus an integer `version`. The `id` is a server-minted UUID with no type prefix; `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits. `version` starts at 1 and increments by exactly 1 on every server-side mutation; reads do not advance it. A second, smaller shape applies to `AssessmentCycle`, `Payment`, `ACCVote`, `Candidate`, and `Ballot`: these entities carry only `id` and `created_at` and have neither an `updated_at` nor a `version` field, because they are either pure event records (votes, payments, ballots) or because their lifecycle is expressed through their child rows rather than through self-mutation.

All monetary values are represented as integer cents. Where a calculation produces a fractional cent — share-factor allocation, late-fee percentage, depreciation accrual — the system rounds half up at the cent step before any subsequent integer-only arithmetic. Where a calculation produces a ratio — the reserve study's funded ratio — the result is a decimal rounded half up to four decimal places.

Time is anchored to a logical clock. An admin-only test-driving capability advances the clock to a supplied `target_timestamp`; the timestamp MUST be strictly greater than or equal to the current clock, and a backward move is rejected with `ERR_TIME_TRAVEL` (HTTP 422). The clock-advance call drives lazy evaluation of every time-gated transition described in §3: charge overdue accrual, violation auto-fining, ACC silent decisions, election status, and lien cooling-off.

### 2.5. Nested Path Resolution and Existence

URL path parameters are resolved left to right. For a route such as a ballot-creation under `/hoa/elections/{id}/ballots`, the election identifier is resolved first, and if it does not match an existing `ElectionCycle` the request returns `ERR_NOT_FOUND` (HTTP 404) without evaluating any downstream body or business rule. The same left-to-right rule applies to every endpoint with multiple path segments.

### 2.6. Optimistic Concurrency Control

Every mutation endpoint listed in §4 that operates on an existing resource accepts an optional `version` field in the request body. When `version` is supplied, the server compares it to the resource's current `version`; on mismatch the mutation is rejected with `ERR_VERSION_CONFLICT` (HTTP 409). When `version` is omitted, the server skips the comparison and applies the change. Creation endpoints do not accept `version`. The same `ERR_VERSION_CONFLICT` is used when a member-level optimistic check on `Member.total_overdue_amount_cents` loses a race during concurrent payment allocation that itself races a lien-release eligibility evaluation: the payment whose allocation first drives `Member.total_overdue_amount_cents` to zero unlocks lien-release eligibility, and the trailing payment, having applied against a stale member version, is rejected with `ERR_VERSION_CONFLICT`.

### 2.7. Validation Ordering

When multiple validation rules apply to a single request, evaluation follows a strict priority. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then role authorization (`ERR_FORBIDDEN`), then path-parameter existence (`ERR_NOT_FOUND`), then state-transition admissibility (`ERR_INVALID_STATE`). Domain-specific checks then apply in the order written in §3 for each workflow: the share-factor sum invariant precedes any other unit-level business check; the lien cooling-off check precedes the lien-recording state check; the ACC-vote board-membership check precedes any vote-tally update; ballot eligibility precedes the voting-window check, which in turn precedes the per-voter uniqueness check; the levy-minimum check precedes any cycle-issuance side effect; the payment positive-amount check precedes any allocation; the ACC begin-review owner-not-delinquent check precedes the reserve-posture check; the segregation-of-duties check on fine-waiver resolutions precedes their persistence; and the candidate-nomination-window check precedes any candidate insert. Resolution-target-type validity is checked at resolution creation, before any acceptance vote can begin. Optimistic concurrency mismatch is reported only after the foregoing checks have passed.

### 2.8. Ledger Conservation and the Member Overdue Aggregate

A single source-of-truth aggregate, `Member.total_overdue_amount_cents`, summarises every dollar a member owes the association. It is computed as the sum, across all units the member owns, of every `AssessmentCharge` row in `OVERDUE` status of the quantity `principal_cents + late_fee_cents − paid_cents`, plus the sum of every `Violation` row in `FINED` status of its `fine_cents`, restricted to violations that have not yet had a payment allocation applied. It excludes charges in `OPEN`, `PAID`, or `WRITTEN_OFF` status and excludes violations in any status other than `FINED`. It is recomputed whenever an `AssessmentCharge` transitions through any of its states, whenever a `Violation` enters `FINED` or moves from `FINED` to `WAIVED`, and whenever a `Payment` is created.

Three downstream gates depend on this aggregate's value. ACC begin-review demands it be exactly zero. Lien creation demands it be at least 180,000 cents — that is, eighteen hundred dollars — and lien recording re-checks the same floor at record time. Lien release demands it be exactly zero. The aggregate's monetary unit is integer cents throughout.

### 2.9. Cascading Side Effects and Version Bumps

Mutations that cross entity boundaries cascade explicitly. Issuing an `AssessmentCycle` creates one `AssessmentCharge` per `Unit` and stamps each charge with `created_at` and `status = OPEN`. Marking a violation `FINED` recomputes `Member.total_overdue_amount_cents` for the owner, and if that recomputation newly carries the owner across the 180,000-cent floor while at least one of the owner's assessment charges has been in `OVERDUE` status for at least sixty days, the owner's unit becomes lien-eligible (the actual lien notice still requires a `SecretaryRole` action). Recording a lien snapshots `principal_cents_at_record` and `mortgage_holder_at_record` and cascades `Unit.lien_status` to `RECORDED`. Releasing a lien cascades `Unit.lien_status` to `RELEASED` and marks the consumed `BoardResolution` as `EXECUTED`. Certifying an election sets the winner's `Member.board_role` to the election's `seat` and demotes any prior holder of that seat to `NONE`; if the prior holder was a sitting member of the three-seat ACC subset and is no longer on the board after the demotion, ACC votes that member cast before the certification remain counted, but any new ACC votes by that member are rejected by the board-membership precondition. Adopting a reserve study whose `posture` is `SPECIAL_ASSESSMENT_REQUIRED` cascades a community-wide block on new ACC begin-review actions for as long as that study remains the most recently adopted. Every mutation refreshes the mutated entity's `updated_at` and increments its `version`.

### 2.10. Status Code Conventions and Idempotency

Successful creation endpoints return HTTP 201. Successful state-transition endpoints and modifications return HTTP 200. The clock-advance endpoint returns HTTP 200. Beginning review on an `ACCRequest` that is already `UNDER_REVIEW` (because the deemed-decision deadline assignment is idempotent) is treated as a state-transition no-op only if the prior status was `SUBMITTED`; calling it on any other status returns `ERR_INVALID_STATE`.

## 3. Business Logic & Workflows

### 3.1. Building the Roster: Units, Members, and Share Factors

The community starts as a roster. A `PresidentRole` registers each homeowner as a `Member` by submitting their `full_name` and `email` — the email must be unique within the HOA. Once members exist, the same role registers their dwellings as `Unit` records carrying an `address`, an `owner_member_id` linking the unit to its homeowner, a four-decimal-place `share_factor` between `0.0001` and `1.0000` representing the unit's pro-rata claim on assessable area, and an optional `mortgage_holder` naming the lender of record (left null when the unit is unencumbered).

The `share_factor` field is the load-bearing piece of this section. The sum of `share_factor` across every `Unit` in the association MUST equal exactly `1.0000` after any insert or update; a request to register a new unit, or to patch the `share_factor` or `mortgage_holder` of an existing one, that would leave the sum at any other value is rejected with `ERR_SHARE_FACTOR_SUM_INVALID` (HTTP 422). Patches that change only `mortgage_holder` and leave `share_factor` untouched still recompute the sum (which trivially remains `1.0000`) and pass the check. The `lien_status` field of a unit is computed and not directly assignable: it is `NONE` while no active `Lien` exists, otherwise it mirrors the active lien's status (`NOTICE_SENT`, `RECORDED`, or `RELEASED`).

Each `Member` carries two computed reflections of community standing. The boolean `eligible_to_vote` is true exactly when the member owns at least one `Unit` and their `total_overdue_amount_cents` is zero at the moment the field is read. The enum `board_role` defaults to `NONE` and is set to one of `PRESIDENT`, `TREASURER`, `SECRETARY`, or `DIRECTOR` only by election certification (see §3.7).

### 3.2. The Assessment Cycle: Levy, Issuance, and Settlement

The `TreasurerRole` opens an assessment by creating an `AssessmentCycle` in `DRAFT`. The cycle carries a `cycle_type` of either `REGULAR` (quarterly) or `SPECIAL` (board-approved levy), a `period_start` instant marking the inclusive beginning of the billable period, a `due_date` after which late fees accrue, a `total_levy_cents` (the integer-cent total the cycle aims to raise), and an optional `approval_resolution_id` linking a `BoardResolution`. The `total_levy_cents` MUST be at least 100 cents; smaller values are rejected with `ERR_LEVY_TOO_SMALL` (HTTP 422). For a `SPECIAL` cycle, `approval_resolution_id` MUST be set and the referenced resolution MUST be in `PASSED` status; for a `REGULAR` cycle the field is optional and ignored if absent.

Issuance moves the cycle from `DRAFT` to `ISSUED` and is the moment charges materialise. The transition requires that the sum of `share_factor` across all units equal exactly `1.0000`, that `total_levy_cents` be at least 100 cents, and — for `SPECIAL` cycles only — that `approval_resolution_id` resolve to a `PASSED` `BoardResolution`. Once those preconditions hold, the server creates one `AssessmentCharge` per `Unit`. Each charge's `principal_cents` is computed by first multiplying `total_levy_cents` by the unit's `share_factor` and rounding the product half up to a whole cent. Because rounding can introduce a few cents of slack, the server then computes the remainder — `total_levy_cents` minus the sum of the rounded principals — and distributes that remainder one cent at a time to units sorted in descending order of `share_factor`, breaking ties by ascending `Unit.id`; if the remainder is positive each chosen unit's `principal_cents` is incremented by one, if negative it is decremented by one, continuing cent-by-cent until the remainder is exhausted. This guarantees that the sum of `principal_cents` across all newly created charges equals `total_levy_cents` exactly. Each charge is stamped with `cycle_id`, `unit_id`, `late_fee_cents = 0`, `paid_cents = 0`, `status = OPEN`, and `created_at = now`. Issuance is run exactly once per cycle.

The `TreasurerRole` may close an issued cycle once every child `AssessmentCharge` has reached a terminal status — that is, every charge is either `PAID` or `WRITTEN_OFF`. The close transitions the cycle to `CLOSED` and refreshes its `updated_at`. Voiding a cycle is available only while it is still in `DRAFT` and only when no charges have yet been created (which, given that charges are created only at issuance, is always the case for a `DRAFT` cycle); the void moves the cycle to `VOIDED`. Any attempt to issue, close, or void from a state that does not permit the transition is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.3. Late Fees, Payments, and the Waterfall

An `AssessmentCharge` begins life `OPEN`. As soon as the logical clock advances past the parent cycle's `due_date` while the charge still carries outstanding balance (`principal_cents + late_fee_cents > paid_cents`), the charge transitions to `OVERDUE`. This transition is evaluated lazily — it fires when the clock-advance capability runs and also any time a read or mutation touches the charge — so an implementation may compute `late_fee_cents` on demand rather than running a daily sweep.

The accrual itself is discretised by missed cycle periods rather than by days. For an overdue charge belonging to a `REGULAR` cycle, the number of missed periods is one plus the integer number of whole 90-day windows elapsed since `due_date` — concretely, take the floor of the elapsed-time-in-days divided by ninety, then add one for the initial overdue period. For a `SPECIAL` cycle the period length is thirty days instead of ninety, computed the same way. The per-period fee is the larger of a flat 2,500 cents (twenty-five dollars) or the result of multiplying `principal_cents` by 0.015 (one and a half percent) and rounding that product half up to a whole cent. The accrued `late_fee_cents` is then the per-period fee multiplied by the number of missed periods, as integer cents. Concretely, a `REGULAR` charge that is 89 days past due has accrued one period; the same charge at 91 days past due has accrued two; at 100 days past due it is still two periods (because the second whole 90-day window has not yet completed). A `SPECIAL` charge at 31 days past due has accrued two periods. Fractional days never advance the fee — the accrual moves in discrete steps at the end of each missed window. Implementations that pro-rate the per-period fee daily will yield different numbers and are incorrect.

Payments are tendered by the homeowner. A `Member` posts a `Payment` carrying their `member_id` (which MUST equal `X-User-ID`) and an `amount_cents` strictly greater than zero; non-positive amounts are rejected with `ERR_AMOUNT_INVALID` (HTTP 422). The server runs a waterfall allocation across that member's units: it orders the eligible targets oldest-overdue-first by the parent cycle's `due_date` ascending, breaking ties by cycle `id` ascending, and within each `AssessmentCharge` it applies the payment first to outstanding `late_fee_cents` and then to outstanding `principal_cents`. `FINED` violations on the member's units are also eligible targets for the same payment. The resulting `allocations` array on the payment is a list of `{charge_id, applied_cents}` entries whose `applied_cents` sums to the payment's `amount_cents`.

A charge moves to `PAID` along one of two paths. The fast path is the pre-deadline path: while the charge is still `OPEN` and its `late_fee_cents` is zero, an allocation that brings `paid_cents + applied_cents` to at least `principal_cents` flips it directly to `PAID`. The slow path is the post-deadline path: when the charge is already `OVERDUE`, an allocation that brings `paid_cents + applied_cents` to at least `principal_cents + late_fee_cents` flips it to `PAID`. In both cases the server updates `paid_cents` and recomputes `Member.total_overdue_amount_cents` for the owner. On the slow path, if the recomputation drives the owner's `total_overdue_amount_cents` to zero and that owner has an active `Lien` in `RECORDED` status, the lien becomes eligible for release — but the release itself still requires the corresponding `BoardResolution` (see §3.6).

An overdue charge whose owner has been through the lien-and-release sequence — meaning the owner's `Unit` carries an active `Lien` in `RELEASED` status whose `released_at` is greater than or equal to the charge's `created_at` — may be written off by the `TreasurerRole`. The write-off transitions the charge directly from `OVERDUE` to `WRITTEN_OFF`, refreshes its `updated_at`, and recomputes the owner's `total_overdue_amount_cents`. Write-off on any other path is rejected with `ERR_INVALID_STATE`.

### 3.4. Architectural Review

Architectural changes flow through the `ACCRequest` entity. A `Member` initiates the request by submitting `unit_id`, `category`, and `description`. The submitter's `X-User-ID` MUST equal the unit's `owner_member_id` at submission time. The `category` is one of `APPEARANCE` or `LANDSCAPING`. The server stamps `submitted_at = now`, sets `submitted_by_member_id` from the caller, computes `deemed_decision_deadline = submitted_at + 30 days`, initialises `yes_votes = 0` and `no_votes = 0`, and places the request in `SUBMITTED` status.

A `SecretaryRole` then begins review, advancing the request from `SUBMITTED` to `UNDER_REVIEW`. This is a guarded transition with two business preconditions on top of the state check. First, the unit's owner — identified by `submitted_by_member_id` — MUST currently have `Member.total_overdue_amount_cents` equal to zero; a delinquent owner is barred with `ERR_OWNER_DELINQUENT` (HTTP 409). Second, the most recently adopted `ReserveStudy` MUST NOT have `posture == SPECIAL_ASSESSMENT_REQUIRED`; if the community is under a special-assessment posture, discretionary modifications are paused for everyone and begin-review is rejected with `ERR_RESERVE_POSTURE_BLOCKS_ACC` (HTTP 409). The begin-review action sets `deemed_decision_deadline = submitted_at + 30 days` idempotently — repeated calls do not move the deadline.

Once `UNDER_REVIEW`, the request is voted on by the three-seat ACC subset of the board: members holding `board_role` in the set `PRESIDENT`, `SECRETARY`, or `DIRECTOR`. The `TreasurerRole` is deliberately not on the ACC and may not cast an ACC vote. Each vote is an `ACCVote` row carrying `request_id`, the caller's `voter_member_id`, a `vote` of either `YES` or `NO`, and a `cast_at` timestamp. Votes by a member who does not hold one of the three ACC seats are rejected with `ERR_NOT_ON_ACC` (HTTP 403) — this check fires before any tally update. Each vote increments either `yes_votes` or `no_votes` on the request. When `yes_votes` reaches at least 2 (and the current instant is still strictly before `deemed_decision_deadline`), the request advances to `APPROVED`; when `no_votes` reaches at least 2 under the same deadline guard, it advances to `DENIED`.

If no decision lands before the deadline, the system resolves the request silently — but the two categories resolve in opposite directions. When the clock first advances to an instant at or after `deemed_decision_deadline` while the request is still `UNDER_REVIEW`, a `LANDSCAPING` request transitions to `AUTO_APPROVED` and an `APPEARANCE` request transitions to `AUTO_DENIED`. The split is deliberate: landscaping is treated as the community's default permissive surface, appearance as the default restrictive surface, and silent inaction is interpreted accordingly. Each silent resolution stamps `updated_at` and records the auto-resolution.

The owner may withdraw their own request at any time before a board decision lands. Withdrawal is the `Member`'s prerogative — the caller's `X-User-ID` MUST equal `submitted_by_member_id`. From `SUBMITTED` the withdrawal needs only the caller-identity check; from `UNDER_REVIEW` it additionally requires that both `yes_votes` and `no_votes` be strictly less than 2 (otherwise the request has already crossed a decision threshold). A successful withdrawal transitions the request to `WITHDRAWN` and stamps `updated_at`. Concurrent begin-review attempts on the same `SUBMITTED` request serialize first-writer-wins on `ACCRequest.status`: exactly one transition to `UNDER_REVIEW` succeeds, and the loser receives `ERR_INVALID_STATE` (HTTP 409).

### 3.5. Violations and Fines

A `Violation` is opened by a `SecretaryRole` or `PresidentRole` against a particular `unit_id`, with a `description` of the infraction. The server stamps `opened_at = now`, sets `opened_by_member_id` from the caller, computes `cure_deadline = opened_at + 14 days`, derives `occurrence_index`, and places the row in `OPEN` status with `fine_cents = 0`.

The `occurrence_index` is a 1-based counter scoped to the unit: it is one more than the number of prior `Violation` rows on the same `unit_id` whose `status` is in the set `FINED`, `CURED`, or `WAIVED` and whose `opened_at` is strictly earlier than this row's `opened_at`. Violations still in `OPEN` status are not counted toward the index. The index drives the fine schedule: occurrence 1 is a warning with `fine_cents = 0`; occurrence 2 is a 5,000-cent fine; occurrence 3 is a 10,000-cent fine; and occurrence 4 or higher is a 20,000-cent fine. The schedule is a tiered lookup with no proration. No rounding is required because the schedule is already in whole cents.

Three exits are available from `OPEN`. The `SecretaryRole` may mark the violation `CURED` at any instant on or before `cure_deadline`; the cure leaves `fine_cents` at zero and refreshes `updated_at`. Past `cure_deadline`, the lazy clock-advance machinery transitions any still-`OPEN` violation to `FINED`, sets `fine_cents` to the schedule value for the violation's `occurrence_index`, and recomputes the owner's `Member.total_overdue_amount_cents`. The fine is now part of the owner's overdue aggregate; if this recomputation newly crosses the 180,000-cent floor and at least one of the owner's assessment charges has been in `OVERDUE` status for at least sixty days, the owner becomes lien-eligible (the lien notice itself still requires a `SecretaryRole` action). A concurrent cure that races the auto-fine across the `cure_deadline` boundary serialises first-writer-wins on `Violation.status`: if the cure POST commits while the current instant is still less than or equal to `cure_deadline`, the violation reaches `CURED` and no fine is posted; otherwise the auto-`FINED` transition wins and the cure is rejected with `ERR_INVALID_STATE`. The third exit is a waiver, available from either `OPEN` or `FINED`, and it requires a successful board resolution.

A waiver is invoked by the `SecretaryRole` and carries a `resolution_id`. There MUST exist a `BoardResolution` with `subject == FINE_WAIVER`, `target_id` equal to the violation's `id`, and `status == PASSED`; the resolution is then consumed (its `status` flips to `EXECUTED`). From `OPEN`, the waiver leaves `fine_cents` at zero and refreshes `updated_at`. From `FINED`, the waiver additionally resets `fine_cents` to zero and recomputes the owner's `total_overdue_amount_cents`. A fine that has been paid (and is therefore no longer part of the overdue aggregate) may not be waived from `FINED`. A waiver resolution carries a hard segregation-of-duties constraint: the `Member` who originally opened the violation (the value of `opened_by_member_id`) MUST NOT also cast a `YES` vote on the corresponding `FINE_WAIVER` resolution. A resolution that records a `YES` vote from the violation's opener is rejected at proposal-or-vote time with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). This is the only place the segregation rule applies, but it applies absolutely: the opener is barred even if they hold a board seat that would otherwise let them vote.

### 3.6. Liens

A `Lien` is the association's escalation lever against persistent delinquency. The `SecretaryRole` creates a lien notice by submitting the `unit_id` of the unit to be encumbered. The creation is admitted only when the unit owner's `Member.total_overdue_amount_cents` is at least 180,000 cents (eighteen hundred dollars) and when at least one `AssessmentCharge` on that unit has been in `OVERDUE` status for at least sixty days as of the current instant; absent either condition the creation is rejected by the standard state/precondition machinery. The new lien lands in `NOTICE_SENT` status. Its `recorded_at` and `released_at` are null at creation; its `principal_cents_at_record` and `mortgage_holder_at_record` are populated only at recordation.

Recordation is invoked by the `PresidentRole` and carries a `resolution_id`. Four preconditions guard the transition from `NOTICE_SENT` to `RECORDED`, and they are checked in this order. First the cooling-off period: the elapsed time between the lien's `created_at` and the current instant MUST be at least 30 days; a recordation attempted before that point is rejected with `ERR_LIEN_COOLING_OFF` (HTTP 409), and the cooling-off rejection takes precedence over every later check so that an impatient board cannot record a lien by piling up other preconditions. Second, there MUST exist a `BoardResolution` with `subject == LIEN_RECORDATION`, `target_id` equal to the lien's `id`, and `status == PASSED`. Third, the unit owner's `Member.total_overdue_amount_cents` MUST still be at least 180,000 cents at the moment of recordation (the floor is re-checked here because the owner may have paid down between notice and record). Fourth, at least one of the unit's `AssessmentCharge` rows MUST currently have been in `OVERDUE` status for at least sixty days. When all four hold, the server sets `recorded_at = now`, snapshots `principal_cents_at_record` from the owner's current `total_overdue_amount_cents`, snapshots `mortgage_holder_at_record` from the unit's current `mortgage_holder` (copied verbatim and used in any subsequent notice text), cascades `Unit.lien_status` to `RECORDED`, refreshes `updated_at`, and increments the lien's `version`. Two simultaneous record attempts on the same lien serialize first-writer-wins on `Lien.status`: exactly one transition from `NOTICE_SENT` to `RECORDED` succeeds, and the loser sees `ERR_INVALID_STATE` (HTTP 409) because the lien has already left `NOTICE_SENT`.

Release is also driven by the `PresidentRole` and carries a `resolution_id`. The release moves the lien from `RECORDED` to `RELEASED` and requires both a `BoardResolution` with `subject == LIEN_RELEASE`, `target_id` equal to the lien's `id`, and `status == PASSED`, and that the unit owner's `Member.total_overdue_amount_cents` equal exactly zero at the moment of release. On success the server sets `released_at = now`, cascades `Unit.lien_status` to `RELEASED`, marks the referenced `BoardResolution` as `EXECUTED`, and refreshes `updated_at` with `version` bumped. The list endpoint over liens supports filtering by `unit_id` and by `status` and is paginated under the rules of §2.3.

### 3.7. Elections

The board refreshes itself through `ElectionCycle` records, one per `seat`. A `PresidentRole` opens the election by specifying which `seat` is up — `PRESIDENT`, `TREASURER`, `SECRETARY`, or `DIRECTOR` — together with three timestamps and an optional `quorum_pct`. The `nomination_open_at` instant inclusively starts the nomination window. The `voting_open_at` instant inclusively opens voting and MUST be strictly later than `nomination_open_at`. The `voting_close_at` instant exclusively closes voting and MUST be strictly later than `voting_open_at`. The `quorum_pct` defaults to 0.40 (forty percent) when omitted and otherwise lies in the closed interval from 0.10 to 1.00 inclusive. The election starts in `NOMINATION`; `winner_candidate_id` is null and `eligible_voter_count_at_open` is null until the voting window opens.

During nomination, any `Member` may register a `Candidate` for the election by submitting their own `member_id` (which MUST equal `X-User-ID`). The candidate MUST have `eligible_to_vote == true` at the instant of nomination — that is, the member must own at least one unit and carry zero overdue. The nomination instant MUST also lie within the half-open interval from `nomination_open_at` inclusive to `voting_open_at` exclusive; outside that interval the registration is rejected with `ERR_NOMINATION_CLOSED` (HTTP 409). The server stamps `nominated_at = now` and initialises `vote_count = 0`. The `nominated_at` timestamp doubles as the tie-break for ranking.

When the clock crosses `voting_open_at` while the election is still `NOMINATION`, the system transitions to `VOTING` and snapshots `eligible_voter_count_at_open` as the count of all `Member` rows whose `eligible_to_vote` is true at that instant. The snapshot is pinned for the remainder of the election. If, however, the clock crosses `voting_open_at` and no `Candidate` rows exist for the election, the election transitions directly to `VOIDED` with no winner and no snapshot.

Ballots are cast during the `VOTING` window. A `Member` submits a `Ballot` carrying the election's `election_id`, the caller's `voter_member_id` (which MUST equal `X-User-ID`), and the `candidate_id` of their choice. Three checks fire in order. The voter MUST currently have `eligible_to_vote == true` AND MUST have had `eligible_to_vote == true` at the `voting_open_at` snapshot; failure on either prong returns `ERR_VOTER_INELIGIBLE` (HTTP 403). The election's `status` MUST equal `VOTING` — equivalently, the current instant lies in the half-open interval from `voting_open_at` inclusive to `voting_close_at` exclusive; a ballot outside that window returns `ERR_VOTING_CLOSED` (HTTP 409). The pair `(election_id, voter_member_id)` MUST be unique across all existing `Ballot` rows; a duplicate is rejected with `ERR_DUPLICATE_BALLOT` (HTTP 409). Two ballots cast for the same election by the same voter at the same instant serialize first-writer-wins on that uniqueness constraint, and the loser also receives `ERR_DUPLICATE_BALLOT`. The candidate identified by `candidate_id` MUST belong to the same election. Each ballot increments the chosen candidate's `vote_count`.

When the clock crosses `voting_close_at` while the election is still `VOTING`, the system tallies. The number of ballots cast (`total_ballots`) is the count of `Ballot` rows scoped to the election. The required ballot threshold is the ceiling of `eligible_voter_count_at_open` multiplied by `quorum_pct` — for example, 100 eligible voters at a 0.40 quorum requires at least 40 ballots. If `total_ballots` is strictly less than that ceiling, the election transitions to `FAILED_QUORUM` with no winner and `winner_candidate_id` left null. Otherwise the candidates are ranked first by `vote_count` descending and then by `nominated_at` ascending (earliest nomination wins ties), and `winner_candidate_id` is set to the top row. The election transitions to `TALLIED`.

Certification is then performed by a `SecretaryRole`, advancing the election from `TALLIED` to `CERTIFIED`. The precondition is simply that `winner_candidate_id` is set (which it is for any non-`FAILED_QUORUM` tally). Certification sets the winner's `Member.board_role` to the election's `seat`. If a prior `Member` already held that `board_role`, the prior holder is demoted to `board_role == NONE`. The demotion is itself a cascade hop: if the prior holder was a sitting member of the three-seat ACC subset and they no longer hold any board seat, any `ACCVote` rows they cast before the certification remain counted (votes are immutable historical records), but any new ACC vote they attempt after certification is rejected by the board-membership precondition with `ERR_NOT_ON_ACC`.

### 3.8. Board Resolutions

Board resolutions are the choke point through which every consequential side effect must pass. Any sitting board member — `PresidentRole`, `TreasurerRole`, `SecretaryRole`, or `DirectorRole` — proposes a `BoardResolution` by submitting a `subject` and a `target_id`. The five admissible subjects are `SPECIAL_ASSESSMENT`, `RESERVE_STUDY_ADOPTION`, `FINE_WAIVER`, `LIEN_RECORDATION`, and `LIEN_RELEASE`. At proposal time the server validates the target. A `SPECIAL_ASSESSMENT` subject requires the `target_id` to resolve to an `AssessmentCycle` in `DRAFT` status. A `RESERVE_STUDY_ADOPTION` subject requires the `target_id` to resolve to a `ReserveStudy` in `DRAFT` status. A `FINE_WAIVER` subject requires the `target_id` to resolve to a `Violation` whose `status` is in the set `OPEN` or `FINED`. A `LIEN_RECORDATION` or `LIEN_RELEASE` subject requires the `target_id` to resolve to an existing `Lien`. Any mismatch — wrong entity type or wrong status — is rejected with `ERR_RESOLUTION_TARGET_INVALID` (HTTP 422). New resolutions land in `PROPOSED` and carry `yes_votes = 0` and `no_votes = 0`.

Voting on a resolution is open to all four board roles. Each vote is recorded with the caller's role and choice of `vote` (`YES` or `NO`). When `yes_votes` reaches at least 3 — a majority of the 4-seat board — the resolution transitions to `PASSED`. When `no_votes` reaches at least 2, or when the current instant exceeds the resolution's `created_at` plus 14 days, the resolution transitions to `FAILED`. A resolution that has reached `PASSED` is consumed by the downstream action it authorised: cycle-issuance for `SPECIAL_ASSESSMENT`, reserve-study-adoption for `RESERVE_STUDY_ADOPTION`, violation-waiver for `FINE_WAIVER`, lien-recordation for `LIEN_RECORDATION`, lien-release for `LIEN_RELEASE`. Consumption flips the resolution from `PASSED` to `EXECUTED`; a resolution in `EXECUTED` status may not be reused. The segregation-of-duties rule described in §3.5 applies during voting on `FINE_WAIVER` resolutions: any `YES` vote cast by the `Member` whose `id` equals the target violation's `opened_by_member_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`.

### 3.9. Reserve Studies and the Funded-Ratio Posture

A `TreasurerRole` produces a `ReserveStudy` to assess the community's capital adequacy. The submission carries a `study_year` calendar-year integer, a non-empty `components` array (each element a record of `component_name`, `replacement_cost_cents`, `useful_life_years`, and `remaining_life_years`), and the HOA's `current_reserve_balance_cents` at the snapshot instant. The study begins in `DRAFT` with `adopted_resolution_id = null` and immediately computes its derived fields.

The `full_funding_target_cents` is the sum across components. For each component the system computes `replacement_cost_cents` multiplied by the quantity (`useful_life_years` minus `remaining_life_years`) divided by `useful_life_years`, rounded half up to a whole cent — this is the component's accrued depreciation at the snapshot. Each component's contribution is rounded to whole cents before the sum is taken; the totals are then added as integers. An implementation that defers rounding until after summing the raw component contributions can drift by a cent at half-cent boundaries and is incorrect.

The `funded_ratio` is `current_reserve_balance_cents` divided by `full_funding_target_cents`, rounded half up to four decimal places. When `full_funding_target_cents` is zero, `funded_ratio` is null (division by zero is not attempted) and `posture` is `OK`. Otherwise the `posture` enum is derived from the ratio's value: `OK` when the ratio is at least 0.70, `RESTRICTED` when the ratio is at least 0.30 but strictly less than 0.70, and `SPECIAL_ASSESSMENT_REQUIRED` when the ratio is strictly less than 0.30. The ratio is recomputed whenever `components` or `current_reserve_balance_cents` is updated.

Adoption is invoked by the `TreasurerRole` and carries a `resolution_id`. The transition from `DRAFT` to `ADOPTED` requires that `adopted_resolution_id` be set on the study and that the referenced `BoardResolution` carry `subject == RESERVE_STUDY_ADOPTION` and `status == PASSED`. On adoption, if the study's `posture` is `SPECIAL_ASSESSMENT_REQUIRED`, the community enters a discretionary-modifications pause: any in-flight `ACCRequest` still in `UNDER_REVIEW` may continue, but any new begin-review attempt — on any existing `SUBMITTED` request or any future submission — is rejected with `ERR_RESERVE_POSTURE_BLOCKS_ACC` for as long as this remains the most recently adopted study. When a newer `ReserveStudy` (whose `study_year` is greater than or equal to the prior one's) itself transitions to `ADOPTED`, the prior `ADOPTED` study is automatically superseded — its status transitions to `SUPERSEDED`. The ACC pause therefore lifts only when a subsequent study with non-`SPECIAL_ASSESSMENT_REQUIRED` posture is adopted.

### 3.10. The Logical Clock

The clock-advance capability is exclusive to the `PresidentRole`. The request carries a `target_timestamp` ISO 8601 instant that MUST be strictly greater than or equal to the current clock; a backward move is rejected with `ERR_TIME_TRAVEL`. On a successful advance, the server returns the new clock value and runs the lazy sweeps in a single pass. Every `AssessmentCharge` whose parent cycle's `due_date` now lies in the past and which still carries outstanding balance is forced into `OVERDUE` (if it is not already), and its `late_fee_cents` is recomputed by the per-period schedule of §3.3. Every `Violation` still in `OPEN` status whose `cure_deadline` is now in the past is transitioned to `FINED`, with `fine_cents` set per the schedule of §3.5. Every `ACCRequest` still in `UNDER_REVIEW` whose `deemed_decision_deadline` is now in the past resolves silently — `AUTO_APPROVED` for `LANDSCAPING`, `AUTO_DENIED` for `APPEARANCE`. Every `ElectionCycle` advances along its time axis: `NOMINATION` to `VOTING` at `voting_open_at` (or to `VOIDED` if no candidates), and `VOTING` to `TALLIED` or `FAILED_QUORUM` at `voting_close_at`. Every affected `Member.total_overdue_amount_cents` is then recomputed in a single pass.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201 on success. Endpoints that transition an existing resource (issue, close, void, begin-review, cure, waive, record, release, adopt, certify, write-off) and read-only fetches return HTTP 200. The clock-advance endpoint returns HTTP 200. All endpoints share the response envelope, header, and validation rules of §2; payloads and side effects are not duplicated here — they are described in the §3 narrative for each workflow.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | `/hoa/units` | Register a Unit and re-validate the share-factor sum invariant | `PresidentRole` |
| GET | `/hoa/units/{id}` | Fetch a unit | `Member`, `SecretaryRole`, `TreasurerRole`, `PresidentRole`, `DirectorRole` |
| PATCH | `/hoa/units/{id}` | Update `share_factor` or `mortgage_holder` and re-validate the sum invariant | `PresidentRole` |
| POST | `/hoa/members` | Register a Member | `PresidentRole` |
| GET | `/hoa/members/{id}` | Fetch a member including `total_overdue_amount_cents` and `board_role` | `Member`, `SecretaryRole`, `TreasurerRole`, `PresidentRole`, `DirectorRole` |
| POST | `/hoa/assessment-cycles` | Create an AssessmentCycle in `DRAFT` | `TreasurerRole` |
| POST | `/hoa/assessment-cycles/{id}/issue` | Issue the cycle: generate one AssessmentCharge per Unit and allocate principal | `TreasurerRole` |
| POST | `/hoa/assessment-cycles/{id}/close` | Close an `ISSUED` cycle once every child charge is `PAID` or `WRITTEN_OFF` | `TreasurerRole` |
| POST | `/hoa/assessment-cycles/{id}/void` | Void a `DRAFT` cycle | `TreasurerRole` |
| GET | `/hoa/assessment-charges/{id}` | Fetch a charge with up-to-date `late_fee_cents` (recomputed lazily) | `Member`, `SecretaryRole`, `TreasurerRole`, `PresidentRole`, `DirectorRole` |
| POST | `/hoa/assessment-charges/{id}/write-off` | Write off an overdue charge after the unit has been through lien release | `TreasurerRole` |
| POST | `/hoa/payments` | Tender a payment; server runs waterfall allocation | `Member` |
| POST | `/hoa/acc-requests` | Submit an ACC request | `Member` |
| POST | `/hoa/acc-requests/{id}/begin-review` | Promote `SUBMITTED` to `UNDER_REVIEW` | `SecretaryRole` |
| POST | `/hoa/acc-requests/{id}/votes` | Cast a YES/NO vote on an ACC request | `PresidentRole`, `SecretaryRole`, `DirectorRole` |
| DELETE | `/hoa/acc-requests/{id}` | Owner withdraws their ACC request | `Member` |
| POST | `/hoa/violations` | Open a violation against a unit | `SecretaryRole`, `PresidentRole` |
| POST | `/hoa/violations/{id}/cure` | Mark a violation cured before `cure_deadline` | `SecretaryRole` |
| POST | `/hoa/violations/{id}/waive` | Waive a violation when a PASSED FINE_WAIVER resolution exists | `SecretaryRole` |
| POST | `/hoa/board-resolutions` | Propose a board resolution | `PresidentRole`, `TreasurerRole`, `SecretaryRole`, `DirectorRole` |
| POST | `/hoa/board-resolutions/{id}/votes` | Cast YES/NO on a board resolution | `PresidentRole`, `TreasurerRole`, `SecretaryRole`, `DirectorRole` |
| POST | `/hoa/elections` | Open an election cycle for one seat | `PresidentRole` |
| POST | `/hoa/elections/{id}/candidates` | Register a candidate | `Member` |
| POST | `/hoa/elections/{id}/ballots` | Cast a ballot | `Member` |
| POST | `/hoa/elections/{id}/certify` | Certify the tally and seat the winner | `SecretaryRole` |
| POST | `/hoa/liens` | Create a Lien notice in `NOTICE_SENT` | `SecretaryRole` |
| POST | `/hoa/liens/{id}/record` | Record the lien after cooling-off and PASSED resolution | `PresidentRole` |
| POST | `/hoa/liens/{id}/release` | Release a recorded lien after balance is fully paid | `PresidentRole` |
| GET | `/hoa/liens` | List liens with optional `unit_id` and `status` filters; paginated | `Member`, `SecretaryRole`, `TreasurerRole`, `PresidentRole`, `DirectorRole` |
| POST | `/hoa/reserve-studies` | Create a ReserveStudy in `DRAFT`; compute `funded_ratio` and `posture` | `TreasurerRole` |
| POST | `/hoa/reserve-studies/{id}/adopt` | Adopt the study after a PASSED `RESERVE_STUDY_ADOPTION` resolution | `TreasurerRole` |
| GET | `/hoa/reserve-studies/{id}` | Fetch a reserve study including `funded_ratio` and `posture` | `Member`, `SecretaryRole`, `TreasurerRole`, `PresidentRole`, `DirectorRole` |
| POST | `/hoa/_clock/advance` | Test-driving capability that advances the logical clock | `PresidentRole` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|------------------|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_SHARE_FACTOR_SUM_INVALID` | 422 |
| `ERR_LIEN_COOLING_OFF` | 409 |
| `ERR_NOT_ON_ACC` | 403 |
| `ERR_VOTER_INELIGIBLE` | 403 |
| `ERR_VOTING_CLOSED` | 409 |
| `ERR_DUPLICATE_BALLOT` | 409 |
| `ERR_LEVY_TOO_SMALL` | 422 |
| `ERR_AMOUNT_INVALID` | 422 |
| `ERR_OWNER_DELINQUENT` | 409 |
| `ERR_RESERVE_POSTURE_BLOCKS_ACC` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOMINATION_CLOSED` | 409 |
| `ERR_RESOLUTION_TARGET_INVALID` | 422 |
| `ERR_DELIVERY_NOT_APPLICABLE` | 422 |
| `ERR_TIME_TRAVEL` | 422 |
