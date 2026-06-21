# Bbbs Mentorship Matching API — Product Requirements Document

## 1. Introduction

Big Brothers Big Sisters runs a one-on-one mentorship program that pairs an adult volunteer (a "Big") with an enrolled child (a "Little") and then shepherds that relationship from first introduction through monthly oversight to a deliberate, documented exit. This API is the system of record for that lifecycle. It must safely move a volunteer through criminal, motor-vehicle, and child-abuse-registry screening before that volunteer is ever offered to a family; it must rank eligible volunteers against a waitlisted child by shared interests, geographic proximity, and pledged capacity; and it must keep an auditable trail of supervision contacts, mentoring activity, and the eventual outcome survey.

The program's integrity rests on two structural commitments that the API enforces directly. First, **one-on-one exclusivity**: a Big in an active relationship may not be bound to a second Little, and the matching engine must refuse to overwrite a pairing it cannot prove it has freshly observed. Second, **segregation of duties**: the people who screen volunteers, the people who propose and confirm matches, and the people who oversee and close them are organizationally separate, and the system rejects any attempt by one actor to both confirm a match and later sign off on its closure. Throughout, a match carries two independent health signals — a relationship lifecycle axis and a compliance posture derived from how recently the parties were contacted and how recently they did anything together — and both must be reconcilable from the persisted record at any time.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming that user's role. If either header is missing, or the role is not one the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation under the matrix in §4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

There are exactly four roles, spelled exactly as follows: `Coordinator`, `BackgroundScreener`, `MatchSpecialist`, and `Supervisor`. A `Coordinator` is the intake and administrative operator who registers volunteers, guardians, and children and who controls the test clock. A `BackgroundScreener` runs and adjudicates background screens but is structurally barred from proposing or confirming matches. A `MatchSpecialist` runs the interest-matching engine, resolves proposals, and conducts the meeting workflow. A `Supervisor` oversees confirmed relationships, completes monthly follow-ups, finalizes exits, and submits outcome surveys.

All four roles are **opaque operator identities**: in each case `X-User-ID` is an operator identifier that is not tied to any persisted entity's `id`, and the server never compares it to a volunteer, guardian, child, or any other resource's identifier for ownership purposes. The server does, however, **record** the acting identity where the workflow demands it. Specifically, when a `MatchSpecialist` accepts a proposal and thereby confirms a match, that specialist's `X-User-ID` is retained as the confirming user of that match; it is later compared — as an operator identity, not as an entity foreign key — against the `X-User-ID` of the `Supervisor` who attempts to finalize that match's exit, which is the basis of the segregation-of-duties rule described in §3.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, must be at least 1, and may be at most 100. The `offset` defaults to 0 when omitted and must be 0 or greater. A `limit` outside the range 1 through 100, or a negative `offset`, is rejected with `ERR_INVALID_REQUEST` (HTTP 422). Lists are returned in ascending order of `created_at` unless a specific endpoint narrative states otherwise. For every list response, the `meta` object additionally carries `limit`, `offset`, `total_count` (the total number of matching records before the page window is applied), and `has_more` (true when records remain beyond the current window).

### 2.4. Common Resource Properties and Versioning

Every resource is assigned a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits, set when the resource is first persisted. Most resources additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that begins at 1 and increases by one on each mutation. One entity is the exception: an activity-log entry is append-only and immutable once written, so it carries only its `id` and `created_at` — it has neither an `updated_at` nor a `version`, because it is never updated after creation.

A successful creation returns HTTP 201; a successful modification of an existing resource returns HTTP 200. Whenever a mutation touches an entity — whether directly or as part of a cascade triggered elsewhere — that entity's `updated_at` is refreshed and its `version` is incremented, so that a reader can always tell that the record has moved.

### 2.5. Optimistic Concurrency on Guarded Writes

Two write operations are guarded by optimistic concurrency control because they bind scarce, exclusive resources. In each case the client must supply a version field carrying the value of the parent's `version` that the client last observed, and the server compares it against the parent's current `version` before proceeding.

The first guarded write is **generating a proposal for a child**. That request must carry `expected_child_version`, holding the `version` of the target child that the specialist last read. Each time a proposal is generated, the child's `version` advances (the prior offer is superseded and the child cycles through its proposal state, changing `open_proposal_id`). Therefore, if another writer has already advanced the child's `version` since the specialist last observed it, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the specialist from issuing a proposal against a child it has not freshly observed.

The second guarded write is **accepting a proposal**. That request must carry `expected_volunteer_version`, holding the `version` of the selected volunteer that the specialist last read. Accepting a proposal binds that volunteer into a one-on-one match. If the volunteer's `version` has advanced since the specialist last observed it — for example, because the volunteer was already bound into another confirmed match, which bumps both its `version` and its `active_match_count` — the accept is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the one-on-one exclusivity invariant. Updating a guardian record likewise carries `expected_guardian_version`, which must equal the guardian's current `version`; only the two named write operations above produce the OCC-specific rejection, while the guardian update simply requires the field as part of its normal mutation contract and increments the guardian's `version` by one on success.

### 2.6. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed priority order so that the earliest applicable failure is the one reported. The order is: (1) authentication of the headers, yielding `ERR_UNAUTHENTICATED`; (2) authorization of the role, yielding `ERR_UNAUTHORIZED`; (3) existence of every referenced resource, validated left-to-right along the URL path and then for any body foreign keys, yielding `ERR_NOT_FOUND`; (4) presence, typing, enum membership, and numeric range of request-body fields, yielding `ERR_INVALID_REQUEST`; (5) the optimistic-concurrency version check on guarded writes, yielding `ERR_STALE_VERSION`; (6) the state-machine precondition that the target resource is in a state from which the requested transition is defined, yielding `ERR_INVALID_STATE`; and only then (7 and beyond) the domain-specific business rules described throughout §3, each with its own error. Pagination-bound checks on list endpoints share the field-validation tier and report `ERR_INVALID_REQUEST`.

### 2.7. Nested Resource Retrieval

Several read endpoints are reached through a parent's path — for example, the screens belonging to a volunteer, the children belonging to a guardian, the proposals or the match or the meetings or the activities or the supervision contacts belonging to a particular match. For any such nested read, each path segment is validated left to right: if the parent named earlier in the path does not exist, the request fails with `ERR_NOT_FOUND` before the child collection is considered. These reverse-reachability reads exist so that, given any record, a client can navigate to every record that references it (for instance, listing proposals filtered by `volunteer_id` recovers every proposal that selected a given volunteer).

### 2.8. Geographic, Capacity, and Precision Conventions

A ZIP code (`home_zip`) is a five-digit string; the **geo cluster** used in proximity scoring is its first three digits. Interest preferences (`interest_tags`) are drawn from a shared controlled vocabulary common to both volunteers and children — for example `SPORTS`, `ARTS`, `STEM`, `OUTDOORS`, `MUSIC`, `COOKING`, and `READING`. All monetary-style or score-style decimal outputs in this system are carried to two decimal places using round-half-up, and each rounding rule states exactly when in the computation the rounding is applied. Day-count comparisons used in compliance scoring are computed as whole days using a floor, and the comparison at each threshold is strict (greater-than), as detailed in §3.

## 3. Business Logic & Workflows

### 3.1. Bringing a Volunteer Through Screening

A volunteer is registered with a `full_name`, a contact `email` that must be unique among volunteers, a `gender` of `MALE`, `FEMALE`, or `NONBINARY`, a five-digit `home_zip`, a list of `interest_tags`, and a `max_weekly_hours` figure pledging the capacity the volunteer offers each week, which must be an integer of at least 1. A newly registered volunteer begins in `APPLIED` with an `active_match_count` of 0 and no `cleared_check_id`.

Screening begins when a `BackgroundScreener` submits a volunteer for screening. This is permitted only while the volunteer is in `APPLIED`, and it cascades the creation of three independent screens at once — one of `check_type` `CRIMINAL`, one `DMV`, and one `CHILD_ABUSE_REGISTRY` — each created in `PENDING` against this volunteer's `volunteer_id`, with `submitted_at` recording when the screen was ordered. The volunteer transitions `APPLIED → SCREENING`. The same operation is also the re-screening entry point: a volunteer already in `ELIGIBLE` may be sent back through screening, but only when that volunteer's `active_match_count` is 0; doing so transitions the volunteer `ELIGIBLE → SCREENING`, creates three fresh `PENDING` screens, and clears the previously stored `cleared_check_id`.

Each `PENDING` screen is adjudicated by a `BackgroundScreener` to either a cleared or a flagged outcome, with the decision supplied as `decision` together with the `adverse_findings` count returned by that screen. A clear decision is permitted only when the adverse findings are within tolerance for the kind of screen: a `CRIMINAL` or a `CHILD_ABUSE_REGISTRY` screen may be cleared only if its `adverse_findings` is exactly 0, whereas a `DMV` screen may be cleared if its `adverse_findings` is at most 1. If the supplied count exceeds the applicable tolerance, the clear is rejected with `ERR_ADVERSE_FINDING_BLOCKS_CLEAR` (HTTP 409) and the screen stays `PENDING`. On a successful clear the screen moves `PENDING → CLEARED`, its `adjudicated_at` is set to the current clock instant, and its `valid_until` is set to the adjudication instant plus twenty-four calendar months. On a flag decision the screen moves `PENDING → FLAGGED`, its `adjudicated_at` is set to the current instant, and its `valid_until` remains null; `FLAGGED` is terminal.

The volunteer's own status changes are bubbled up from the screens rather than driven directly. When the third screen of a volunteer reaches `CLEARED` — so that all three screens are simultaneously `CLEARED` with a `valid_until` in the future — the volunteer advances `SCREENING → ELIGIBLE` and its `cleared_check_id` is set to the `id` of the `CRIMINAL` screen, the single screen tracked as the representative cleared check. Conversely, the moment any one screen reaches `FLAGGED`, the volunteer is driven `SCREENING → SCREENING_FAILED`, which is terminal; as a compensation cascade, any still-`OFFERED` proposal naming this volunteer is declined and the affected child is returned to the waitlist. A flag arising during a re-screening cycle drives the same `SCREENING_FAILED` outcome and the same compensation.

### 3.2. Validity, Expiry, and the Test Clock

The `cleared_check_id` on a volunteer is not a permanent stamp; it points at the `CRIMINAL` screen only while all three of that volunteer's screens are jointly valid. A screen is currently valid only while its `status` is `CLEARED` and the current clock instant is strictly earlier than its `valid_until`. If any one of the three screens has expired or been flagged, the volunteer holds no valid cleared check and is not eligible to be offered to a family.

An administrative clock-advance capability, reserved to a `Coordinator`, sets the server clock to a supplied UTC instant provided as `to_iso8601`. Advancing the clock fires the due-date and expiry sweeps. Any `CLEARED` screen whose `valid_until` is now at or before the current instant is moved `CLEARED → EXPIRED`; when an expiring screen is the one a volunteer's `cleared_check_id` points at, that pointer is cleared. The same clock advance is the moment at which overdue supervision follow-ups are evaluated for the missed outcome described in §3.5.

### 3.3. Enrolling Children and Generating Proposals

Families enter through a guardian, registered with a `full_name`, a contact `email` unique among guardians, and a `consent_on_file` flag that defaults to false. A guardian record can be updated — chiefly to record that consent is now on file — and that update is the only mutation a guardian receives. A child (a Little) is enrolled under a guardian's `guardian_id` with a `first_name`, an `age` that must be between 6 and 16 inclusive at enrollment, a `gender` of `MALE`, `FEMALE`, or `NONBINARY`, a five-digit `home_zip`, a list of `interest_tags` drawn from the same controlled vocabulary as volunteers use, and an optional `requires_same_gender` preference (defaulting to false) expressing whether the guardian insists on a same-gender Big. A child begins `WAITLISTED` with no `open_proposal_id`.

A `MatchSpecialist` proposes a match for a waitlisted child, which runs the matching engine and creates an offer. This is permitted only while the child is `WAITLISTED`; the child's guardian must have `consent_on_file` set to true, failing which the request is rejected with `ERR_CONSENT_NOT_ON_FILE` (HTTP 409); and the candidate pool of eligible volunteers must be non-empty, failing which the request is rejected with `ERR_NO_ELIGIBLE_VOLUNTEER` (HTTP 409). On success the engine creates a `MatchProposal` in `OFFERED` recording the child's `child_id`, the selected volunteer's `volunteer_id`, the `compatibility_score` of that volunteer, and the `candidate_pool_size` (the number of eligible volunteers the engine considered); the child transitions `WAITLISTED → PROPOSED` and its `open_proposal_id` is set to the new proposal's `id`. If the child already had an `OFFERED` proposal, that prior proposal is moved `OFFERED → SUPERSEDED` and the child momentarily reverts toward the waitlist before being re-attached to the fresh proposal; this re-proposal is exactly the operation guarded by `expected_child_version` as described in §2.5, and it increments the child's `version` by one.

**Defining the eligible candidate pool.** A volunteer qualifies for a given child's pool only when the volunteer's `status` is `ELIGIBLE`, the volunteer's `active_match_count` is 0, the volunteer holds a non-null `cleared_check_id`, and the gender preference is satisfied — that is, either the child does not require a same-gender Big (`requires_same_gender` is false) or the volunteer's `gender` equals the child's `gender`. If no volunteer satisfies all four conditions, the pool is empty and the proposal fails as above.

**Scoring and selecting.** Each eligible volunteer is scored against the child by combining three components. The **interest component** is the Jaccard similarity of their interest tag sets: the number of tags present in both `interest_tags` lists divided by the number of distinct tags present in either list, taken as 0 when the union is empty; this yields a value from 0 to 1. The **geo component** is 1.0 when the volunteer's geo cluster equals the child's geo cluster (the first three digits of each `home_zip` match) and 0.0 otherwise. The **capacity component** is the volunteer's `max_weekly_hours` capped at 10 and then divided by 10, yielding a value from 0 to 1 (a volunteer pledging 10 or more hours contributes the full 1.0). The volunteer's score is the interest component weighted by 0.6, plus the geo component weighted by 0.25, plus the capacity component weighted by 0.15. The three weighted terms are summed first and the single resulting sum is then rounded half-up to two decimal places — the rounding is applied once to the final sum, never to the individual components. The volunteer with the highest rounded score is selected, and that rounded value is stored as the proposal's `compatibility_score`. When two or more volunteers tie on the rounded score, the volunteer with the earliest `created_at` is selected; ties are never broken by `id`.

### 3.4. Resolving a Proposal into a Confirmed Match

A `MatchSpecialist` resolves an `OFFERED` proposal by either accepting or declining it. Declining requires a `decline_reason` of `VOLUNTEER_UNAVAILABLE`, `GUARDIAN_DECLINED`, or `POOR_FIT`; it moves the proposal `OFFERED → DECLINED` and bubbles the child `PROPOSED → WAITLISTED`, clearing the child's `open_proposal_id`. (The same `PROPOSED → WAITLISTED` revert is what happens to the child whenever its open offer is declined or superseded, and it occurs only once the child has no remaining `OFFERED` proposal.)

Accepting an `OFFERED` proposal binds the relationship. The selected volunteer must still be `ELIGIBLE`, failing which the accept is rejected with `ERR_VOLUNTEER_NOT_ELIGIBLE` (HTTP 409), and the selected volunteer's `active_match_count` must be 0, failing which it is rejected with `ERR_VOLUNTEER_AT_CAPACITY` (HTTP 409) — this is the one-on-one exclusivity gate. As described in §2.5, the accept must also carry `expected_volunteer_version` matching the volunteer's current `version`, or it is rejected with `ERR_STALE_VERSION`. On success the proposal becomes `ACCEPTED`, and a `Match` is created in `relationship_status` `CONFIRMED` recording the `child_id`, the `volunteer_id`, and the accepted `proposal_id`, with `confirmed_at` set to the current instant. Creating the match bubbles two parent transitions: the child advances `PROPOSED → MATCHED` (clearing its `open_proposal_id`), and the volunteer advances `ELIGIBLE → MATCHED` with its `active_match_count` incremented to 1; the accept also increments the volunteer's `version` by one. A new match's `compliance_status` and `closure_reason` are not yet meaningful — `closure_reason` is null until closure, and `activated_at`, `last_activity_at`, and `last_contact_at` are all null at this stage, with `total_mentoring_minutes` at 0.

### 3.5. The Introduction Meeting and Activation

A match advances along its relationship axis only through the meeting it schedules, never by a direct call on the match itself. A `MatchSpecialist` schedules a `MatchMeeting` for a match by supplying a `scheduled_start`, a `scheduled_end`, and a free-text `location`; the meeting is created in `SCHEDULED`. The `scheduled_end` must be strictly later than the `scheduled_start`, failing which the request is rejected with `ERR_MEETING_WINDOW_INVALID` (HTTP 422).

Before a new meeting is persisted, two overlap guards run. The **per-match overlap** guard treats the new window as half-open over `[scheduled_start, scheduled_end)` and compares it against every other meeting on the *same* match that is still in `SCHEDULED` or `HELD`: the two collide when the new start is earlier than the existing end and the existing start is earlier than the new end. Sharing a single endpoint is permitted — a new meeting starting exactly when an existing one ends (or ending exactly when an existing one starts) is back-to-back, not an overlap. A collision yields `ERR_MEETING_OVERLAP` (HTTP 409). The **per-guardian double-booking** guard resolves the guardian of the child on this match and gathers every meeting still in `SCHEDULED` or `HELD` across all matches of *every* child of that same guardian — including meetings on other children's matches. Each existing window is treated as closed and inflated on both sides by sixty minutes; the new meeting collides when the new start is earlier than the existing end plus sixty minutes and the existing start is earlier than the new end plus sixty minutes. Because the intervals are closed and buffer-inflated, a shared endpoint collides, and so does any positive gap strictly smaller than sixty minutes. A collision yields `ERR_GUARDIAN_DOUBLE_BOOKED` (HTTP 409).

Holding the meeting is permitted only when the meeting is `SCHEDULED` and its parent match is in `CONFIRMED`; if the parent match is not in `CONFIRMED`, the hold is rejected with `ERR_MATCH_NOT_READY_FOR_MEETING` (HTTP 409). A successful hold records optional `outcome_notes`, moves the meeting `SCHEDULED → HELD`, and advances the parent match `CONFIRMED → INTRODUCED`. A scheduled meeting that does not take place is instead marked as a no-show, moving it `SCHEDULED → NO_SHOW` with no effect on the match. From `HELD`, the meeting branches two ways with divergent effects. Affirming a held meeting — permitted only while it is `HELD` — moves it `HELD → AFFIRMED` and advances the parent match `INTRODUCED → ACTIVE`, stamping the match's `activated_at` with the current instant and opening the first supervision follow-up (in `OPEN`) whose `due_at` is the activation instant plus thirty days. Rescinding a held meeting — also permitted only while it is `HELD` — instead moves it `HELD → RESCINDED`, leaving the parent match in `INTRODUCED` so that a fresh meeting may be scheduled.

### 3.6. Monthly Supervision and Activity Tracking

Once a match is `ACTIVE`, two streams of record-keeping run in parallel. The first is **mentoring activity**: an activity entry is appended to the match recording an `occurred_at` instant, a `duration_minutes` value that must be an integer of at least 1, and an `activity_type` of `OUTING`, `CALL`, `MEAL`, `TUTORING`, or `EVENT`. Such an entry is created in `LOGGED` and is append-only — it is never voided or edited. Appending an entry recomputes the match's `total_mentoring_minutes` as the sum of `duration_minutes` over the match's `LOGGED` activity entries, refreshes the match's `last_activity_at` to the latest entry's `occurred_at`, and recomputes the match's compliance posture.

The second stream is **supervision follow-up**. Each follow-up is a `SupervisionContact` carrying the supervised match's `match_id`, a system-set `due_at`, a `contacted_at` instant that is null while the follow-up is `OPEN`, a `party` of `BIG`, `LITTLE`, or `GUARDIAN` naming whom the supervisor reached, and a `concern_flag` (defaulting to false) recording whether a safety or fit concern was noted. A `Supervisor` completes an `OPEN` follow-up — permitted only while the parent match is `ACTIVE`, failing which the completion is rejected with `ERR_MATCH_NOT_ACTIVE` (HTTP 409) — by supplying `contacted_at` and `party`. Completion moves the follow-up `OPEN → COMPLETED`, sets its `contacted_at`, and opens the next follow-up in `OPEN` with a `due_at` of the just-recorded `contacted_at` plus thirty days; it then recomputes the match's `compliance_status` and refreshes the match's `last_contact_at` to that `contacted_at`. Each follow-up's `due_at` thus advances on the monthly cadence of thirty days, measured from the previous contact (or, for the very first follow-up, from the match's `activated_at`). Separately, when the clock is advanced past a still-`OPEN` follow-up's `due_at` and a newer `OPEN` follow-up already exists for that match, the stale follow-up is swept `OPEN → MISSED`, which itself recomputes the match's compliance posture.

**Deriving the compliance posture.** A match's `compliance_status` is one of `GREEN`, `AMBER`, or `RED`, recomputed whenever supervision contacts or activity change and re-evaluated at read time against the current clock. If the match is not in `relationship_status` `ACTIVE`, its posture is `GREEN`. Otherwise the system computes the whole number of days since the last completed contact as the floor of the elapsed time since `last_contact_at` (or, if no contact has been completed, since `activated_at`), and likewise the whole number of days since the last activity as the floor of the elapsed time since `last_activity_at` (or since `activated_at` if none). The posture is `RED` if the days since contact exceed 60, or if the match has any supervision follow-up in `MISSED`. Failing that, the posture is `AMBER` if the days since contact exceed 30, or the days since activity exceed 45. Otherwise the posture is `GREEN`. Each threshold comparison is strict — exactly 60 days since contact, for instance, is not yet `RED`.

### 3.7. Exiting a Match and the Outcome Survey

An exit is opened as a `DRAFT` `ExitTransition` against a match by either a `Supervisor` or a `MatchSpecialist`, recording the match's `match_id`, an `exit_type` of `SUCCESSFUL_CLOSURE` or `EARLY_TERMINATION`, an `initiated_by` of `BIG`, `LITTLE`, `GUARDIAN`, or `AGENCY`, and a `reason_code` of `GRADUATION`, `RELOCATION`, `LOST_INTEREST`, `SAFETY_CONCERN`, or `PROGRAM_VIOLATION`. At the moment the exit is opened, `survey_required` is computed and pinned: it is true exactly when the `exit_type` is `SUCCESSFUL_CLOSURE`, or when the match had reached `ACTIVE` at any point before the exit; otherwise it is false.

Finalizing the exit is reserved to a `Supervisor` and closes the match. It is permitted only while the exit is in `DRAFT` and the parent match is in `INTRODUCED` or `ACTIVE`; an exit against a match in any other relationship state is rejected with `ERR_INVALID_STATE` (HTTP 409). Critically, the finalizing supervisor must not be the same operator who confirmed the match: if the `X-User-ID` finalizing the exit equals the `X-User-ID` recorded as the confirming match specialist, the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). On a successful finalize, the exit moves `DRAFT → FINALIZED` and the match is closed — `relationship_status` becomes `CLOSED` and the match's `closure_reason` is set from the exit's `exit_type`. The closure cascades: every still-`OPEN` supervision follow-up on the match is swept to `MISSED`, and — when the match was closed out of `INTRODUCED` rather than `ACTIVE` — any still-`SCHEDULED` meeting on the match is swept to `NO_SHOW`. The closure also bubbles its parents: the volunteer returns `MATCHED → ELIGIBLE` (its `active_match_count` dropping back to 0, which frees the Big to be re-matched), and the child's fate depends on the closure reason — an `EARLY_TERMINATION` returns the child `MATCHED → WAITLISTED` so the Little can be matched again, whereas a `SUCCESSFUL_CLOSURE` moves the child `MATCHED → INACTIVE`.

After a match is `CLOSED`, a `Supervisor` may submit its single, immutable Outcome Survey, supplying the closed match's `match_id`, the finalized exit's `exit_transition_id`, a `relationship_quality` Likert rating from 1 to 5, a `child_outcome` Likert rating from 1 to 5, and a `would_rematch` flag. The survey is accepted only when the parent match is `CLOSED`, the referenced exit's `survey_required` is true (otherwise `ERR_SURVEY_NOT_REQUIRED`, HTTP 409), and no prior survey exists for this `match_id` (otherwise `ERR_SURVEY_ALREADY_EXISTS`, HTTP 409). On submission the system computes the **Strength-of-Relationship index**: a base equal to half the `relationship_quality` plus half the `child_outcome`, plus a rematch bonus of 0.5 when `would_rematch` is true and 0 otherwise, with the result rounded half-up to two decimal places and stored as `composite_score`. The survey's `outcome_band` is then banded from that score: `STRONG` when the score is at least 4.0, `MODERATE` when it is at least 2.5 but below 4.0, and `WEAK` below 2.5 — each band boundary is an inclusive lower edge.

## 4. Endpoint Definitions

A successful creation of a new resource returns HTTP 201. A successful read or a successful modification of an existing resource (including state transitions on an existing resource) returns HTTP 200. All endpoints emit the standard envelope of §2.2; failures carry one of the error codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server clock to a fixed UTC instant; fire expiry and overdue sweeps | Coordinator |
| POST | `/volunteers` | Register a volunteer | Coordinator, MatchSpecialist |
| GET | `/volunteers/{id}` | Get a volunteer | Coordinator, MatchSpecialist, BackgroundScreener, Supervisor |
| GET | `/volunteers` | List volunteers (filterable by `status`) | Coordinator, MatchSpecialist, BackgroundScreener, Supervisor |
| POST | `/volunteers/{id}/submit-screening` | Begin or re-begin screening; cascades three pending checks | BackgroundScreener |
| POST | `/volunteers/{id}/deactivate` | Move an unmatched eligible volunteer to inactive | MatchSpecialist |
| GET | `/volunteers/{id}/background-checks` | List a volunteer's background checks | Coordinator, MatchSpecialist, BackgroundScreener, Supervisor |
| GET | `/background-checks/{id}` | Get a background check | Coordinator, BackgroundScreener, MatchSpecialist, Supervisor |
| POST | `/background-checks/{id}/adjudicate` | Clear or flag a pending check | BackgroundScreener |
| POST | `/guardians` | Register a guardian | Coordinator, MatchSpecialist |
| GET | `/guardians/{id}` | Get a guardian | Coordinator, MatchSpecialist, Supervisor |
| PATCH | `/guardians/{id}` | Update a guardian (chiefly to record consent) | Coordinator, MatchSpecialist |
| GET | `/guardians/{id}/children` | List a guardian's children | Coordinator, MatchSpecialist, Supervisor |
| POST | `/children` | Enroll a child | Coordinator, MatchSpecialist |
| GET | `/children/{id}` | Get a child | Coordinator, MatchSpecialist, Supervisor |
| GET | `/children` | List children (filterable by `status`, `guardian_id`) | Coordinator, MatchSpecialist, Supervisor |
| POST | `/children/{id}/propose-match` | Run the matching engine and create an offered proposal | MatchSpecialist |
| GET | `/children/{id}/proposals` | List a child's proposals | Coordinator, MatchSpecialist, Supervisor |
| GET | `/children/{id}/match` | List a child's match (0 or 1) | Coordinator, MatchSpecialist, Supervisor |
| GET | `/match-proposals/{id}` | Get a proposal | Coordinator, MatchSpecialist, Supervisor |
| GET | `/match-proposals` | List proposals (filterable by `child_id`, `volunteer_id`, `status`) | Coordinator, MatchSpecialist, Supervisor |
| POST | `/match-proposals/{id}/accept` | Accept a proposal; create a confirmed match | MatchSpecialist |
| POST | `/match-proposals/{id}/decline` | Decline a proposal; revert the child to the waitlist | MatchSpecialist |
| GET | `/match-proposals/{id}/match` | List the match produced by a proposal (0 or 1) | Coordinator, MatchSpecialist, Supervisor |
| GET | `/matches/{id}` | Get a match | Coordinator, MatchSpecialist, Supervisor |
| GET | `/matches` | List matches (filterable by `relationship_status`, `compliance_status`, `volunteer_id`) | Coordinator, MatchSpecialist, Supervisor |
| POST | `/matches/{id}/meetings` | Schedule an introduction meeting | MatchSpecialist |
| GET | `/matches/{id}/meetings` | List a match's meetings | Coordinator, MatchSpecialist, Supervisor |
| POST | `/matches/{id}/activities` | Append an activity log entry | MatchSpecialist, Supervisor |
| GET | `/matches/{id}/activities` | List a match's activity entries | Coordinator, MatchSpecialist, Supervisor |
| POST | `/matches/{id}/exit-transitions` | Open a draft exit transition | Supervisor, MatchSpecialist |
| GET | `/matches/{id}/exit-transitions` | List a match's exit transitions | Coordinator, MatchSpecialist, Supervisor |
| GET | `/matches/{id}/supervision-contacts` | List a match's supervision contacts | Coordinator, MatchSpecialist, Supervisor |
| GET | `/matches/{id}/survey` | List a match's outcome survey (0 or 1) | Coordinator, MatchSpecialist, Supervisor |
| GET | `/match-meetings/{id}` | Get a meeting | Coordinator, MatchSpecialist, Supervisor |
| POST | `/match-meetings/{id}/hold` | Mark a scheduled meeting held; advance match to introduced | MatchSpecialist |
| POST | `/match-meetings/{id}/no-show` | Mark a scheduled meeting a no-show | MatchSpecialist |
| POST | `/match-meetings/{id}/affirm` | Affirm a held meeting; activate the match | MatchSpecialist |
| POST | `/match-meetings/{id}/rescind` | Rescind a held meeting; match stays introduced | MatchSpecialist |
| GET | `/supervision-contacts/{id}` | Get a supervision contact | Coordinator, MatchSpecialist, Supervisor |
| POST | `/supervision-contacts/{id}/complete` | Complete a monthly follow-up; open the next | Supervisor |
| GET | `/exit-transitions/{id}` | Get an exit transition | Coordinator, MatchSpecialist, Supervisor |
| GET | `/exit-transitions/{id}/survey` | List the survey for an exit transition (0 or 1) | Coordinator, MatchSpecialist, Supervisor |
| POST | `/exit-transitions/{id}/finalize` | Finalize a draft exit; close the match | Supervisor |
| POST | `/outcome-surveys` | Submit the outcome survey for a closed match | Supervisor |
| GET | `/outcome-surveys/{id}` | Get an outcome survey | Coordinator, MatchSpecialist, Supervisor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ADVERSE_FINDING_BLOCKS_CLEAR` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_CONSENT_NOT_ON_FILE` | 409 |
| `ERR_VOLUNTEER_NOT_ELIGIBLE` | 409 |
| `ERR_VOLUNTEER_AT_CAPACITY` | 409 |
| `ERR_NO_ELIGIBLE_VOLUNTEER` | 409 |
| `ERR_MATCH_NOT_READY_FOR_MEETING` | 409 |
| `ERR_MATCH_NOT_ACTIVE` | 409 |
| `ERR_SURVEY_NOT_REQUIRED` | 409 |
| `ERR_SURVEY_ALREADY_EXISTS` | 409 |
| `ERR_MEETING_WINDOW_INVALID` | 422 |
| `ERR_MEETING_OVERLAP` | 409 |
| `ERR_GUARDIAN_DOUBLE_BOOKED` | 409 |
