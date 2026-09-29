# Concussion Protocol & Return-to-Play Administration API — Product Requirements Document

## 1. Introduction

Professional sports leagues no longer treat head-injury management as a matter of club discretion. A modern concussion protocol is a chain of custody: a player's cognitive baseline is measured before the season, a removal from play can be forced by an official who does not work for the club, the examination that follows must be attended by a clinician with no club allegiance, and the decision that finally returns the player to contact is reserved for an independent neurological consultant. Every one of those links has to be recorded, timed, and afterwards provable to a league auditor — because when the chain is broken, the league fines the club.

This document specifies the API that administers that chain end to end. It governs pre-season baseline neurocognitive testing and the events that invalidate a baseline; sideline evaluation with unaffiliated-observer removal authority; the locker-room examination and independent consultant attendance; diagnosis documentation with mandatory removal from play; the five-stage graduated return-to-participation ladder with per-stage medical sign-off; independent consultant final clearance as the sole gate on return to contact; protocol compliance auditing with escalating club fines and case freezing; league injury reporting with public designation rules; and prolonged-symptom, post-season and off-season monitoring.

Four authority layers coexist in the system and must remain separately reachable and separately gated: club medical staff, the league's unaffiliated observers, the independent consultant panel, and the league audit function. The design consequence is that segregation of duties is not advisory — the clinician who documents a diagnosis may not grant the final clearance, the auditor who opens an audit may not price it, and the auditor who prices it may not close it. Every collection in the API is mounted under the `/concussion-program` prefix, with the sole exception of the administrative clock endpoint described in §2.4.

## 2. Global Specifications & System-Wide Principles

This section fixes the contract-level behaviour that applies to every endpoint: authentication, envelope shape, pagination, identity and time, the order in which refusals are decided, concurrency control, and the cross-cutting arithmetic of compliance scoring, fine escalation and slot conservation.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts. If either header is absent, or if `X-User-Role` is not exactly one of the six recognised role names, the request is refused with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well formed but the declared role is not among the roles the target endpoint permits, the refusal is `ERR_UNAUTHORIZED` (HTTP 403).

The six roles are `LeagueAdmin`, `ClubPhysician`, `UnaffiliatedObserver`, `IndependentConsultant`, `ClubComplianceOfficer`, and `LeagueAuditor`. Wherever this document says an operation is available to "all roles", it means all six of those names.

- **`LeagueAdmin`** — league football-operations administration. Owns the reference data (clubs, clinicians, games), the credentialing register, baseline invalidation, the operational sweep, and the logical clock. `X-User-ID` for this role is an **opaque** operator identifier not tied to any persisted entity: the server may accept and log it but never compares it to any entity's `id`.
- **`ClubPhysician`** — club-affiliated physician. `X-User-ID` is the `id` of the acting `Clinician`, and that clinician's `affiliation` must be `CLUB_AFFILIATED`. Ownership checks compare that clinician's `club_id` to the `club_id` of the player or case being acted on.
- **`UnaffiliatedObserver`** — league-appointed unaffiliated neurotrauma observer. `X-User-ID` is the `id` of the acting `Clinician`, whose `affiliation` must be `UNAFFILIATED_OBSERVER`. The observer holds removal authority but performs no screens, no diagnoses and no clearances.
- **`IndependentConsultant`** — independent neurological consultant. `X-User-ID` is the `id` of the acting `Clinician`, whose `affiliation` must be `INDEPENDENT_CONSULTANT` and whose `club_id` must be null. Ownership checks compare `X-User-ID` to the `inc_clinician_id` recorded on the clearance being decided.
- **`ClubComplianceOfficer`** — club compliance officer. `X-User-ID` is the `id` of the acting `Club` itself; ownership checks on any resource that references a club compare that resource's club foreign key (an audit's `club_id`, a case's `club_id`, a player's `club_id`) to `X-User-ID`.
- **`LeagueAuditor`** — league compliance auditor. `X-User-ID` is an **opaque** operator identifier not tied to any persisted entity. The server records it — as `opened_by_user_id`, `findings_issued_by_user_id` and `closed_by_user_id` on the audits that auditor touches — but never compares it to any entity's `id`. Segregation of duties is enforced by comparing those recorded opaque identifiers to one another.

For the three clinician-backed roles, if `X-User-ID` does not resolve to an existing `Clinician`, or resolves to a clinician whose `affiliation` does not match the declared role, the request is refused with `ERR_ROLE_IDENTITY_MISMATCH` (HTTP 403). When a `ClubComplianceOfficer` acts on another club's resource, or a `ClubPhysician` acts on a player or case belonging to another club, the refusal is `ERR_CLUB_SCOPE_VIOLATION` (HTTP 403).

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the logical clock of §2.4 rather than from wall-clock time, so it echoes whatever instant the clock currently holds.
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

List endpoints accept two query parameters. `limit` caps the number of rows returned; it defaults to 10, has a minimum of 1 and a maximum of 100. `offset` is the number of rows to skip; it defaults to 0 and its minimum is 0. A `limit` outside the range from 1 to 100 inclusive, or a negative `offset`, is a schema violation and is refused with `ERR_INVALID_REQUEST`.

Unless a specific endpoint says otherwise, every list endpoint returns its rows sorted by `created_at` in ascending order.

The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the number of rows matching the filters before pagination is applied and `has_more` indicates whether rows remain beyond the current page.

### 2.4. Resource Identity, Timestamps and the Logical Clock

Every one of the eleven persisted resource types — clubs, clinicians, players, games, baseline tests, sideline evaluations, concussion cases, return steps, consultant clearances, protocol audits and injury report entries — carries the same four system-managed properties, and all four are present on every row of every one of those types:

- `id` (string): a server-minted UUID. It carries no type prefix; the raw UUID is the identifier.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits (for example `2026-09-13T18:19:00.000Z`) recording when the row was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp, in the same format, refreshed on every mutation of the row — including mutations the server performs on its own initiative, such as a derived score being recomputed or a case being frozen by a club sanction.
- `version` (integer): a counter that starts at 1 on creation and increments by exactly 1 on every mutation of the row. Two clients that both mutate a row therefore see it advance twice.

All datetime comparisons in this specification, and every datetime the server stamps on a row, read from a **logical clock** rather than wall-clock time. An administrative endpoint sets that clock from a supplied `current_utc` instant, and the clock may be moved forwards or backwards; no other request ever advances it implicitly. Until the clock has been set explicitly for the first time, it reads `2026-08-01T00:00:00Z`. This is the mechanism by which deadline breaches, dwell windows, rest buffers, clearance expiry, the prolonged-symptom line, the off-season boundary and the injury-report filing window all become reachable. That endpoint is the single exception to the `/concussion-program` mount: it lives at `POST /_clock/set_current_utc` and returns the `current_utc` value now in force.

Path identifiers are validated left to right. Every path in this API addresses exactly one resource and names its identifier `{id}`, so path resolution is a single lookup: if the `{id}` does not resolve, the request is refused with the not-found error belonging to that resource type before any body validation, state check or business rule is evaluated. Foreign keys supplied inside a request body are resolved after path identifiers, and a body key that names a missing row produces the not-found error for the *referenced* type, not for the path resource.

### 2.5. The Refusal Ladder: Validation Precedence

When one request violates several rules at once, exactly one error is returned: the one belonging to the earliest applicable rung of the ladder below. The ladder is global — it holds across every endpoint — and implementations must evaluate it in this order rather than in whatever order is convenient.

1. **Header authentication.** Both `X-User-ID` and `X-User-Role` present, and `X-User-Role` one of the six role names, else `ERR_UNAUTHENTICATED` (401). Applies to every endpoint.
2. **Role authorisation.** The acting role appears on the endpoint's permitted-role list, else `ERR_UNAUTHORIZED` (403). Applies to every endpoint.
3. **Request and query schema.** Required fields present, JSON types correct, enum members recognised, and integers inside their declared ranges — `symptom_score` from 0 to 20, `composite_score` from 0 to 100, `reaction_time_ms` from 200 to 1500, `stage_index` from 1 to 5, `exposure_days` from 0 to 30, `jersey_number` from 0 to 99, `week_index` from 1 to 18, `season_year` from 2020 to 2100, `exemption_slots_total` from 1 to 5, `limit` from 1 to 100, `offset` at least 0 — all bounds inclusive. This rung also refuses an empty `violation_codes` array on a findings request, a clinician whose `club_id` is supplied when `affiliation` is not `CLUB_AFFILIATED` or omitted when it is, a game whose `home_club_id` equals its `away_club_id`, a `market_code` that is not exactly three uppercase letters, and a `ClubPhysician` declaring a `trigger_source` that role may not declare. Body keys the endpoint does not recognise are ignored rather than refused, and an absent or empty request body is treated as an empty JSON object (so its required fields are then reported missing). The error is `ERR_INVALID_REQUEST` (400) and it applies to every endpoint.
4. **Path existence.** The `{id}` in the path resolves. `ERR_CLUB_NOT_FOUND` (404) for `GET /concussion-program/clubs/{id}`, `GET /concussion-program/clubs/{id}/players` and `GET /concussion-program/clubs/{id}/compliance-summary`; `ERR_CLINICIAN_NOT_FOUND` (404) for `GET /concussion-program/clinicians/{id}` and `POST /concussion-program/clinicians/{id}/suspend`; `ERR_PLAYER_NOT_FOUND` (404) for `GET /concussion-program/players/{id}`; `ERR_GAME_NOT_FOUND` (404) for `GET /concussion-program/games/{id}` and `POST /concussion-program/games/{id}/advance-status`; `ERR_EVALUATION_NOT_FOUND` (404) for the single-evaluation read and all five evaluation action endpoints; `ERR_CASE_NOT_FOUND` (404) for the single-case read and all five case action endpoints; and `ERR_RESOURCE_NOT_FOUND` (404) for the single-resource reads and action endpoints of baseline tests, return steps, consultant clearances, protocol audits and injury report entries.
5. **Body foreign-key existence.** Every foreign key supplied in a request body — `club_id`, `player_id`, `game_id`, `inc_clinician_id`, `case_id`, `sideline_evaluation_id` — resolves to an existing row, else the matching not-found error for the referenced type (`ERR_CLUB_NOT_FOUND`, `ERR_PLAYER_NOT_FOUND`, `ERR_GAME_NOT_FOUND`, `ERR_CLINICIAN_NOT_FOUND`, `ERR_CASE_NOT_FOUND` or `ERR_EVALUATION_NOT_FOUND`), all at HTTP 404. This rung guards clinician creation, player creation, game creation, baseline filing, evaluation initiation, the final-clearance request, injury-report filing and audit opening.
6. **Role identity.** For the three clinician-backed roles, `X-User-ID` is an existing `Clinician` whose `affiliation` matches the declared role — `ClubPhysician` pairs with `CLUB_AFFILIATED`, `UnaffiliatedObserver` with `UNAFFILIATED_OBSERVER`, `IndependentConsultant` with `INDEPENDENT_CONSULTANT` — else `ERR_ROLE_IDENTITY_MISMATCH` (403). Applies to every endpoint whose permitted roles include one of those three.
7. **Club-officer scope.** For `ClubComplianceOfficer`, `X-User-ID` equals the club of the target resource — the audit's `club_id`, the case's `club_id`, or the player's `club_id`. Otherwise `ERR_CLUB_SCOPE_VIOLATION` (403). Applies to player creation, roster-exemption grants, audit responses, injury-report filing and injury-report amendment.
8. **Physician scope.** For `ClubPhysician`, the acting clinician's `club_id` equals the club of the player or case being acted on, else `ERR_CLUB_SCOPE_VIOLATION` (403). Applies to baseline filing, evaluation initiation, all five evaluation action endpoints, stage creation, stage evaluation, the final-clearance request, return to contact and symptom checks.
9. **Credential standing.** The acting clinician's `status` is `ACTIVE`, else `ERR_CLINICIAN_SUSPENDED` (409). This rung also applies to the *referenced* consultant: the `inc_clinician_id` named on a locker-room-exam request or on a final-clearance request must itself be `ACTIVE`.
10. **Resource from-state.** The target row is in a status the requested transition permits. `ERR_RESOURCE_STATE_INVALID` (409) for a game advance the game's `status` does not allow, for invalidating a baseline test that is not `VALID`, and for amending an injury report entry that is not `FILED` or `LATE_FILED`. `ERR_EVALUATION_STATE_INVALID` (409) for the five evaluation actions. `ERR_STEP_STATE_INVALID` (409) when the return step is not `IN_PROGRESS`. `ERR_CLEARANCE_STATE_INVALID` (409) when the consultant clearance is not `PENDING`. `ERR_AUDIT_STATE_INVALID` (409) for findings, response and close. `ERR_CASE_STATE_INVALID` (409) for the five case actions, where the permitted from-states are: stage creation — `MANDATORY_REMOVAL` or `RTP_IN_PROGRESS`; final-clearance request — `MANDATORY_REMOVAL` or `RTP_IN_PROGRESS`; return to contact — `PENDING_INC_CLEARANCE` only; roster exemption — `MANDATORY_REMOVAL`, `RTP_IN_PROGRESS`, `PENDING_INC_CLEARANCE` or `STAGE_FROZEN`; symptom check — any status at all, `CLEARED_FOR_CONTACT` included, because post-clearance and off-season monitoring writes are deliberately permitted on a cleared case. Two deferrals are intentional at this rung: `STAGE_FROZEN` is *not* rejected here for stage creation, for the final-clearance request or for return to contact, so that rung 11 reports the more specific `ERR_CASE_STAGE_FROZEN` on all three; and a `MANDATORY_REMOVAL` case asking for final clearance is *not* rejected here either, so that rung 34 reports `ERR_NO_RETURN_STEPS_RECORDED`.
11. **Freeze guard.** The owning case is not `STAGE_FROZEN` and the owning club's `status` is not `SANCTIONED`, else `ERR_CASE_STAGE_FROZEN` (409). Applies to exactly four operations: stage creation, stage evaluation, the final-clearance request and return to contact.
12. **Optimistic concurrency.** `expected_player_version` matches the current `version` of the player on baseline filing, else `ERR_STALE_PLAYER_VERSION` (412); `expected_case_version` matches the current `version` of the case on a final-clearance request, else `ERR_STALE_CASE_VERSION` (412). See §2.6.
13. `ERR_MANDATORY_REMOVAL_ENFORCED` (409) — on-field clearance of an evaluation that carries mandatory removal, a non-empty `no_go_signs` list, or a `screen_symptom_score` above 0.
14. `ERR_SAME_GAME_RETURN_PROHIBITED` (409) — on-field clearance for a player who already has a `DIAGNOSED` or `HELD_OUT_INCONCLUSIVE` evaluation in the same game.
15. `ERR_NO_GO_SIGNS_PRESENT` (409) — concluding an examination as `NO_CONCUSSION` when the screen recorded at least one no-go sign.
16. `ERR_LOCKER_ROOM_EXAM_TOO_SHORT` (409) — recording any examination conclusion, whether a diagnosis or a no-concussion outcome, before the minimum examination duration has elapsed.
17. `ERR_HEIGHTENED_REVIEW_CLINICIAN_REQUIRED` (403) — the diagnosing clinician signing off a stage while the case carries heightened review. Applies to stage evaluation.
18. `ERR_SEGREGATION_OF_DUTIES` (403) — the auditor who opened an audit issuing its findings, or the auditor who issued the findings closing the audit. Applies to findings and close, and the comparison is skipped whenever the field being compared against is null.
19. `ERR_INC_NOT_INDEPENDENT` (422) — the consultant named on a final-clearance request is not an `INDEPENDENT_CONSULTANT` with a null `club_id`, or is the case's `diagnosing_clinician_id`, or is the clinician who attended that case's locker-room examination.
20. `ERR_EXAM_INC_INELIGIBLE` (422) — the consultant named for a locker-room examination is neither `UNAFFILIATED_OBSERVER` nor `INDEPENDENT_CONSULTANT`, or is the evaluation's `evaluating_clinician_id`.
21. `ERR_INC_ASSIGNMENT_MISMATCH` (403) — a consultant other than the clearance's `inc_clinician_id` deciding it.
22. `ERR_PLAYER_CLUB_MISMATCH` (422) — the player's club is neither the home nor the away club of the referenced game. Applies to evaluation initiation and injury-report filing.
23. `ERR_CLINICIAN_CREDENTIAL_EXPIRED` (422) — the acting clinician's `credential_expires_at` is not strictly after the logical clock; the referenced consultant's credential is checked the same way. Applies to every clinician-role write endpoint.
24. `ERR_GAME_NOT_IN_PROGRESS` (409) — the referenced game is not `IN_PROGRESS`. Applies to evaluation initiation, screening and on-field clearance.
25. `ERR_INC_EXAM_WINDOW_CONFLICT` (409) — the consultant's requested examination block collides with one of that consultant's existing blocks.
26. `ERR_STAGE_REST_BUFFER_VIOLATION` (409) — starting a stage before the previous stage's rest buffer has elapsed.
27. `ERR_STAGE_DWELL_NOT_MET` (409) — passing a stage before its dwell has elapsed. Not checked on the symptom-recurrence branch.
28. `ERR_RETURN_BEFORE_EARLIEST_DATE` (409) — returning to contact before the case's `earliest_return_at`.
29. `ERR_INC_CLEARANCE_EXPIRED` (409) — returning to contact when the case's most recent clearance is `EXPIRED`, or its `expires_at` is at or before the logical clock.
30. `ERR_REPORT_WINDOW_NOT_OPEN` (409) — filing an injury report before the window opens.
31. `ERR_REPORT_WINDOW_CLOSED` (409) — filing or amending an injury report at or after kickoff.
32. `ERR_STAGE_SEQUENCE_VIOLATION` (422) — the requested `stage_index` is not exactly one greater than the case's `rtp_stage`.
33. `ERR_STEP_ALREADY_IN_PROGRESS` (409) — starting a stage while another return step on the case is still `IN_PROGRESS`.
34. `ERR_NO_RETURN_STEPS_RECORDED` (422) — requesting final clearance for a case with no return steps at all.
35. `ERR_RTP_STAGES_INCOMPLETE` (422) — requesting final clearance, or approving one, when any stage from 1 to 5 lacks a `PASSED`, non-`REVOKED` step.
36. `ERR_INC_CLEARANCE_MISSING` (409) — returning to contact with no `APPROVED` clearance on the case.
37. Baseline readiness on return to contact: `ERR_BASELINE_NOT_ESTABLISHED` (422) when the player's `baseline_status` is `NONE`, and `ERR_BASELINE_RETEST_REQUIRED` (422) when it is `RETEST_REQUIRED`.
38. `ERR_OPEN_CASE_EXISTS` (409) — diagnosing a player who already has a case whose `case_status` is anything other than `CLEARED_FOR_CONTACT`.
39. `ERR_SYMPTOM_OUTCOME_MISMATCH` (422) — the declared stage outcome contradicts the symptom score supplied with it.
40. `ERR_INJURY_DESIGNATION_MISMATCH` (422) — the filed or amended `designation` differs from the freshly recomputed `required_designation`.
41. `ERR_DUPLICATE_INJURY_REPORT` (409) — a second injury report entry for the same combination of `game_id` and `player_id`.
42. `ERR_AUDIT_RESPONSE_ROUNDS_EXHAUSTED` (409) — a club filing more responses on one audit than the response-round ceiling allows.
43. `ERR_EXEMPTION_ALREADY_GRANTED` (409) — requesting a roster exemption for a case whose `roster_exemption_status` is already `GRANTED` or `RELEASED`.
44. `ERR_UNIQUENESS_VIOLATION` (409) — a duplicate `market_code` across clubs, a duplicate `license_number` across clinicians, or a duplicate `jersey_number` within one club.
45. `ERR_NO_EXEMPTION_SLOTS` (409) — granting a roster exemption when the club has no slot available.
46. `ERR_CLUB_FINE_CAP_EXCEEDED` (409) — issuing findings whose fine would push the club's outstanding total above the season cap.

### 2.6. Optimistic Concurrency on Players and Cases

Two write endpoints supersede a sibling record and therefore require the caller to prove it read the parent before writing. In both cases the version field is a **required** input, not an optional hint, and no other endpoint in this API accepts a version field at all. Each is validated at the schema rung as an integer of at least 0, with no upper bound.

Filing a baseline test rewrites the subject player's readiness posture, so `POST /concussion-program/baseline-tests` must carry `expected_player_version` holding the `version` of the player the client last read. If that value does not equal the player's current `version` — for instance because a diagnosis has since flipped `baseline_status` to `RETEST_REQUIRED` — the request is rejected with `ERR_STALE_PLAYER_VERSION` (HTTP 412), and the client must re-read the player before retrying. A successful filing increments the player's `version` by 1.

Requesting final consultant clearance supersedes any clearance still `PENDING` on the case and moves the case into `PENDING_INC_CLEARANCE`, so `POST /concussion-program/concussion-cases/{id}/inc-clearances` must carry `expected_case_version` holding the `version` of the case the client last read. Any earlier write to that case — a stage pass, a revocation, a club-posture freeze — has already advanced its `version`, so a stale value is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412). A successful request increments the case's `version` by 1.

### 2.7. Clinician Credentialing and Authority Classes

A clinician's `affiliation` fixes which authority layer that clinician belongs to and is one of exactly three values: `CLUB_AFFILIATED`, `UNAFFILIATED_OBSERVER`, or `INDEPENDENT_CONSULTANT`. A `club_id` is required when and only when the affiliation is `CLUB_AFFILIATED`; supplying it for either of the other two affiliations is a schema violation refused with `ERR_INVALID_REQUEST`, as is omitting it for a club-affiliated clinician.

Credentialing has two independent gates. The first is `status`, which is `ACTIVE` on creation and can become `SUSPENDED`; `suspension_reason` is null while the clinician is `ACTIVE` and carries the league's stated reason once suspended. The second is `credential_expires_at`, the instant at which league credentialing lapses: an action is refused with `ERR_CLINICIAN_CREDENTIAL_EXPIRED` at or after that instant, so the credential is valid only while the logical clock is strictly earlier than it. Both gates apply to the acting clinician on every clinician-role write, and both also apply to a consultant merely *named* in a request body rather than acting — the `inc_clinician_id` on a locker-room-exam request and on a final-clearance request is checked for suspension and for credential expiry exactly as the caller is.

Each consultant also carries `cases_cleared_count`, which starts at 0 and counts the approved clearances credited to that consultant whose cases went on to reach `CLEARED_FOR_CONTACT`.

### 2.8. Club Compliance Posture, Escalation Tiers and the Penalty Ledger

Each club carries two compliance scores that deliberately disagree. `compliance_score` is the **preliminary** figure: it starts at 100 and is the greater of 0 and 100 minus the sum, taken over every audit of that club whose `status` is `FINDINGS_ISSUED`, `CLUB_RESPONDED` or `CLOSED_UPHELD`, of the weights of that audit's `violation_codes`. `adjudicated_compliance_score` is the **adjudicated** figure, computed by exactly the same arithmetic but including only audits whose `status` is `CLOSED_UPHELD`. Audits that are still `OPEN`, and audits that closed dismissed, are excluded from both figures. A code that appears twice inside one audit's array is charged twice — once per occurrence.

Violation weights are: `UNAUTHORIZED_SAME_GAME_RETURN` 25 points, `MISSING_INC_CLEARANCE` 20, `MISSED_MANDATORY_REMOVAL` 18, `EVALUATION_DEADLINE_BREACH` 15, `INCOMPLETE_LOCKER_ROOM_EXAM` 12, `BASELINE_TEST_MISSING` 8, and `LATE_INJURY_REPORT` 6. Both scores are whole points floored at 0.

The preliminary score is the figure that drives everything punitive. `escalation_tier` is `TIER_0` when `compliance_score` is at least 90, `TIER_1` when it lies between 75 and 89 inclusive, `TIER_2` when it lies between 60 and 74 inclusive, and `TIER_3` when it is below 60. Separately, the club's `status` is `ACTIVE` when `compliance_score` is at least 90, `PROBATION` when it lies between 70 and 89 inclusive, and `SANCTIONED` when it is below 70. Both band sets are closed intervals exactly as written; a club scoring exactly 89 is `TIER_1` and on `PROBATION`, and a club scoring exactly 70 is on `PROBATION` rather than `SANCTIONED`.

Whenever an audit's findings are issued or revised, an audit is responded to, an audit is closed, or the operational sweep runs, the server re-derives the club's whole posture in a **pinned seven-step order that must not be rearranged**:

1. Recompute `compliance_score` (the preliminary variant).
2. Recompute `adjudicated_compliance_score` (the adjudicated variant).
3. Recompute `outstanding_fine_cents` as the sum of `assessed_fine_cents` over the club's audits whose `status` is `FINDINGS_ISSUED`, `CLUB_RESPONDED` or `CLOSED_UPHELD`.
4. Recompute `open_violation_count` as the number of the club's audits whose `status` is `OPEN`, `FINDINGS_ISSUED` or `CLUB_RESPONDED`.
5. Re-derive `escalation_tier` from the fresh `compliance_score` using the tier bands above.
6. Re-derive the club's `status` from the fresh `compliance_score` using the posture bands above.
7. Walk the club's concussion cases in ascending `created_at` order and propagate: where the club is now `SANCTIONED` and a case's `case_status` is `RTP_IN_PROGRESS` or `PENDING_INC_CLEARANCE`, record `frozen_from_status` as the current `case_status` and set `case_status` to `STAGE_FROZEN`; where the club is no longer `SANCTIONED` and a case is `STAGE_FROZEN`, restore `case_status` to the recorded `frozen_from_status` and set `frozen_from_status` back to null; and in every case whose `case_status` is not `CLEARED_FOR_CONTACT`, set `heightened_review_required` to true exactly when the club's `status` is `PROBATION` or `SANCTIONED` and to false otherwise.

The routine reaches its fixed point in a single pass: no later step alters an input of an earlier one. The club's `version` and `updated_at` advance only where the routine actually changes at least one of the club's own six derived figures, and a case's only where step 7 actually changes that case — so re-issuing findings that reproduce the codes and exposure the audit already carried leaves both the club row and every case row untouched. Critically, the escalation tier used to *price* an audit is read before step 1 of this routine runs — see §3.9.

Because a club may not be fined without limit in one season, the total `outstanding_fine_cents` that would result from issuing findings must not exceed the season cap of 150000000 cents; findings that would breach it are refused with `ERR_CLUB_FINE_CAP_EXCEEDED`.

### 2.9. Roster Exemption Slot Conservation

Each club declares `exemption_slots_total`, the number of concussion roster exemptions it may hold simultaneously; the value must lie between 1 and 5 inclusive and defaults to 3 when the club is created without one. Against that total the server maintains two derived counters: `exemption_slots_used` is the number of that club's cases whose `roster_exemption_status` is `GRANTED`, and `exemption_slots_available` is `exemption_slots_total` minus `exemption_slots_used`. Cases whose exemption status is `NONE` or `RELEASED` hold no slot.

The two counters are conserved: at every observable instant they sum to `exemption_slots_total`, and the used count never leaves the range from 0 to the total inclusive. A grant that would drive the available count below 0 is refused with `ERR_NO_EXEMPTION_SLOTS` rather than being clamped to 0.

### 2.10. Numeric Precision and Rounding Discipline

Scores, points, day counts and slot counts are whole integers throughout; `severity_index` and both compliance scores are integers, and the only rounding inside the severity computation is a half-up rounding applied to the baseline term *before* that term is capped. Money is always whole cents — there are no fractional-cent values anywhere in the system, and no monetary field is ever expressed in dollars.

Fine arithmetic rounds **half up, twice, in a fixed order**: once for each violation line, and then once more after the escalation multiplier is applied to the summed lines. Summing unrounded line values and rounding a single time at the end produces a different, incorrect result; the two-stage discipline is normative. The intermediate exposure factor is an exact rational and is never pre-rounded.

Timestamps are compared to second precision, and the derived instants the server stamps (`projected_return_at`, `earliest_return_at`, `validity_expires_at`, `protocol_deadline_at`, `inc_block_ends_at`, `min_start_at`, `dwell_complete_at`, `expires_at`, `report_window_opens_at`, `report_window_closes_at`) are millisecond-exact ISO 8601 UTC values with no rounding to day or hour boundaries.

### 2.11. Boundary Conventions for Timed Windows

This protocol mixes two interval conventions deliberately, and confusing them changes observable behaviour at exactly one instant.

**Trailing buffers and dwells are half-open, so adjacency is allowed.** A stage may not start before its `min_start_at`, but starting at exactly `min_start_at` is accepted — the forbidden window runs from the previous stage's sign-off instant up to, but not including, `min_start_at`. Likewise a stage may not be passed before its `dwell_complete_at`, but a pass at exactly `dwell_complete_at` is accepted. In the same family, the post-clearance publication window that softens a player's public designation is half-open: at exactly 72 hours after clearance the window has already closed.

**The consultant's examination block is closed at both ends, so touching endpoints collide.** A consultant's 30-minute block runs from the instant the examination starts to `inc_block_ends_at` inclusive, and a second examination requested at exactly the instant a previous block ends is refused with `ERR_INC_EXAM_WINDOW_CONFLICT`; one second later it is accepted. This is the opposite of the rest-buffer convention above and is intentional.

**Deadlines, expiries and calendar lines are inclusive at the boundary.** A protocol deadline is breached at or after `protocol_deadline_at`; a baseline test expires at or after `validity_expires_at`; a clearance expires at or after `expires_at`; a credential is lapsed at or after `credential_expires_at`; the prolonged-symptom line trips at exactly 21 elapsed days; and the off-season boundary trips at or after its instant. The injury-report window is inclusive on the left of each of its interior boundaries and exclusive on the right.

### 2.12. Collection Reads and Filter Parameters

Every collection read supports `limit` and `offset` plus a set of exact-match filters. A filter value that is not a recognised member of the field's enumeration, or is otherwise ill-typed, is refused with `ERR_INVALID_REQUEST`. Integer filters are type-checked but, apart from `stage_index` which is bounded to 1 through 5, are not range-checked — `season_year` and `week_index` accept any integer at all as a filter, including values outside the ranges rung 3 of §2.5 imposes on request bodies. Identifier-valued filters (`club_id`, `player_id`, `game_id`, `case_id`, `sideline_evaluation_id`, `prior_case_id` and the several `*_clinician_id` filters) are matched literally against stored values with no existence check, so an unknown identifier simply yields an empty page; only an empty-string value for such a filter is refused with `ERR_INVALID_REQUEST`. The `auto_opened` filter accepts `true`, `True`, `TRUE` and `1` as true and `false`, `False`, `FALSE` and `0` as false, refusing anything else.

- `GET /concussion-program/clubs/{id}/players` filters on `availability_status` and `baseline_status`.
- `GET /concussion-program/clinicians` filters on `club_id`, `affiliation` and `status`.
- `GET /concussion-program/players` filters on `club_id`, `availability_status`, `baseline_status` and `public_injury_designation`.
- `GET /concussion-program/games` filters on `season_year`, `week_index`, `home_club_id`, `away_club_id` and `status`.
- `GET /concussion-program/baseline-tests` filters on `player_id`, `administered_by_clinician_id`, `season_year` and `status`.
- `GET /concussion-program/sideline-evaluations` filters on `player_id`, `game_id`, `initiating_clinician_id`, `evaluating_clinician_id`, `inc_clinician_id`, `status` and `trigger_source`.
- `GET /concussion-program/concussion-cases` filters on `player_id`, `club_id`, `sideline_evaluation_id`, `diagnosing_clinician_id`, `prior_case_id`, `case_status`, `monitoring_status`, `roster_exemption_status` and `season_year`.
- `GET /concussion-program/return-steps` filters on `case_id`, `cleared_by_clinician_id`, `stage_index` and `status`.
- `GET /concussion-program/inc-clearances` filters on `case_id`, `inc_clinician_id`, `requested_by_clinician_id` and `status`.
- `GET /concussion-program/protocol-audits` filters on `club_id`, `case_id`, `sideline_evaluation_id`, `status` and `auto_opened`.
- `GET /concussion-program/injury-report-entries` filters on `game_id`, `player_id`, `club_id`, `status` and `designation`.

One read is not a plain projection of a stored row. The club compliance summary at `GET /concussion-program/clubs/{id}/compliance-summary` returns a computed object whose members are `club_id`, `compliance_score`, `adjudicated_compliance_score`, `escalation_tier`, `status`, `outstanding_fine_cents`, `open_violation_count`, `exemption_slots_total`, `exemption_slots_used`, `exemption_slots_available` and `frozen_case_count`, the last being the number of that club's cases whose `case_status` is `STAGE_FROZEN`. Every member is derived by the posture routine of §2.8 and the slot ledger of §2.9 rather than stored independently. This read is restricted to `LeagueAdmin`, `LeagueAuditor` and `ClubComplianceOfficer`; the three clinician-backed roles may read every other collection but not this one.

## 3. Business Logic & Workflows

### 3.1. League Reference Data and the Credentialing Register

Before any protocol activity can occur, a `LeagueAdmin` populates the league's reference data. A club is registered with a `name` between 1 and 80 characters and a `market_code` of exactly three uppercase letters that must be unique across all clubs; a collision on that code is refused with `ERR_UNIQUENESS_VIOLATION`. Optionally the registration also carries `exemption_slots_total`. Everything else about a club is derived: it opens with `compliance_score` and `adjudicated_compliance_score` both at 100, `escalation_tier` at `TIER_0`, `status` at `ACTIVE`, `outstanding_fine_cents` at 0, `open_violation_count` at 0, `exemption_slots_used` at 0, and `exemption_slots_available` equal to its declared total.

Clinicians are registered next, each with a `full_name`, an `affiliation`, a `license_number` that must be unique across all clinicians, a `credential_expires_at`, and — only for club-affiliated clinicians — a `club_id`. A newly registered clinician is `ACTIVE` with `cases_cleared_count` at 0 and no `suspension_reason`.

Players may be registered either by a `LeagueAdmin` or by the `ClubComplianceOfficer` of the club in question, and carry a `club_id`, a `full_name`, a `jersey_number` from 0 to 99 that must be unique inside that club, and a `position` drawn from `QB`, `RB`, `WR`, `TE`, `OL`, `DL`, `LB`, `DB`, `K` and `P`. A new player starts with `baseline_status` at `NONE`, `availability_status` at `AVAILABLE`, `public_injury_designation` at `NONE`, and `diagnosed_case_count` at 0.

Games are registered by a `LeagueAdmin` with a `season_year`, a `week_index`, a `home_club_id`, an `away_club_id` that must differ from the home club, and a `kickoff_at`. From the kickoff instant the server derives the injury-reporting window described in §3.9, stamping `report_window_opens_at` at four days before kickoff and `report_window_closes_at` at ninety minutes before it. A game begins `SCHEDULED`. A `LeagueAdmin` walks it forward one step at a time by supplying a `to_status`: `SCHEDULED` becomes `IN_PROGRESS`, and `IN_PROGRESS` becomes `FINAL`, each advance incrementing the game's `version` by 1. Skipping straight from `SCHEDULED` to `FINAL` is rejected with `ERR_RESOURCE_STATE_INVALID`, as is any advance whose declared from-state does not match reality. Once a game is `FINAL`, no sideline evaluation belonging to it may afterwards be screened or cleared on field; such attempts are refused with `ERR_GAME_NOT_IN_PROGRESS`.

Suspension is the league's emergency brake on a clinician, and it cascades. A `LeagueAdmin` suspends a clinician with a stated `reason`, moving that clinician from `ACTIVE` to `SUSPENDED` and recording the reason as `suspension_reason`; suspending an already-suspended clinician is refused with `ERR_CLINICIAN_SUSPENDED`. The cascade then reaches every consultant clearance still `PENDING` whose `inc_clinician_id` is the suspended clinician: each such clearance becomes `SUPERSEDED`, and each such clearance's case returns from `PENDING_INC_CLEARANCE` to `RTP_IN_PROGRESS` **without any return step being revoked and without `rtp_stage` moving**. The suspended clinician's `version` increments by 1, and so does the `version` of every clearance and every case the cascade touched.

### 3.2. Baseline Neurocognitive Testing and Retest Obligations

A `ClubPhysician` files a pre-season baseline for a player of their own club, supplying the `player_id`, the `season_year` the baseline is filed for, a `composite_score`, a `reaction_time_ms`, a `symptom_score` capturing the player's resting symptom burden, and the `expected_player_version` demanded by §2.6. The server stamps `administered_by_clinician_id` from the acting physician's identifier, `administered_at` from the logical clock, `status` as `VALID`, `retest_required_reason` as `NONE`, and `validity_expires_at` at exactly 365 days after `administered_at`.

Filing a fresh baseline supersedes the old one. Where the player already had a test with `status` `VALID`, that older row moves `VALID → SUPERSEDED`, the player's `baseline_status` is re-resolved, and the player's `version` increments by 1.

A player's `baseline_status` is never set directly; it is resolved from the player's baseline rows every time one of them changes, and only rows whose `status` is `VALID` are considered at all — `SUPERSEDED`, `INVALIDATED` and `EXPIRED` rows are ignored entirely. When no `VALID` row remains, `baseline_status` is `NONE`. Otherwise the server picks the candidate with the greatest `administered_at`, breaking ties by taking the more recently created row, and reads that row's `retest_required_reason`: anything other than `NONE` yields `RETEST_REQUIRED`, and `NONE` yields `VALID`.

Three events put a retest on the books, each recording a distinct reason on the affected row. A diagnosis stamps `NEW_DIAGNOSIS` (see §3.5). A `LeagueAdmin` may administratively invalidate a baseline with a stated `reason`, moving it `VALID → INVALIDATED` and stamping `retest_required_reason` as `ADMIN_INVALIDATION`; the player's `baseline_status` is then re-resolved — becoming `NONE` when no other `VALID` row survives — and the player's `version` increments by 1. Invalidating a row that is not `VALID` is refused with `ERR_RESOURCE_STATE_INVALID`. Finally the operational sweep expires a baseline at or after its `validity_expires_at`, moving it `VALID → EXPIRED` with `retest_required_reason` set to `SEASON_ROLLOVER`, re-resolving the player's `baseline_status` to `NONE` where no other `VALID` row exists, and incrementing the player's `version` by 1.

The consequence surfaces at the very end of the protocol: a player whose `baseline_status` is `RETEST_REQUIRED` cannot return to contact until a fresh baseline is filed, and a player who never had one at all cannot either. Filing a new baseline mid-protocol is the intended remedy, because the new row carries `retest_required_reason` `NONE` and becomes the resolved latest.

### 3.3. Game-Day Removal: Initiating and Screening a Sideline Evaluation

A sideline evaluation opens the protocol on game day. It is initiated with a `player_id`, a `game_id`, and a `trigger_source` naming who required it, and the server stamps `initiating_clinician_id` from the caller, `initiated_at` from the logical clock, `status` as `INITIATED`, `diagnosis_outcome` as `PENDING`, and `no_go_signs` as an empty list. The referenced game must be `IN_PROGRESS`, and the player's club must be either the home or the away club of that game — otherwise the request is refused with `ERR_PLAYER_CLUB_MISMATCH`.

Two roles may initiate, and their authority differs. A `ClubPhysician` may initiate only for players of their own club, and may declare a `trigger_source` of `CLUB_MEDICAL_STAFF`, `GAME_OFFICIAL`, `VIDEO_SPOTTER` or `COACH`. An `UnaffiliatedObserver` may initiate for **any** player in the game regardless of club, and is the only role permitted to declare `trigger_source` `UNAFFILIATED_OBSERVER` — this is the observer's removal authority, and no other role can invoke it. A `ClubPhysician` naming `UNAFFILIATED_OBSERVER` is refused at the schema rung with `ERR_INVALID_REQUEST`, decided from the declared role and trigger alone before any identifier in the body is resolved; an `UnaffiliatedObserver` may in turn declare any of the five trigger sources.

From the trigger the server derives `mandatory_removal`, which is true exactly when `trigger_source` is `UNAFFILIATED_OBSERVER`, `GAME_OFFICIAL` or `VIDEO_SPOTTER`, and false for `CLUB_MEDICAL_STAFF` and `COACH`. That single boolean sets the protocol clock: `protocol_deadline_at` falls 15 minutes after `initiated_at` when `mandatory_removal` is true, and 45 minutes after it otherwise. When `mandatory_removal` is true the player can never be cleared on field, no matter what the screen finds.

The screen itself is performed by a `ClubPhysician` of the player's own club, moving the evaluation `INITIATED → SCREENED`. The request carries the `no_go_signs` observed and a `symptom_score`, which the server records as `screen_symptom_score`; it also stamps `evaluating_clinician_id` from the caller and `screened_at` from the logical clock, and increments the evaluation's `version` by 1. A no-go sign is one of `LOSS_OF_CONSCIOUSNESS`, `ATAXIA`, `CONFUSION`, `AMNESIA`, `BLANK_STARE` or `MOTOR_INCOORDINATION`, and the list may legitimately be empty. Screening requires the evaluation to be `INITIATED` (otherwise `ERR_EVALUATION_STATE_INVALID`), the game to be `IN_PROGRESS` (otherwise `ERR_GAME_NOT_IN_PROGRESS`), and the acting clinician to be club-affiliated to the player's club (otherwise `ERR_CLUB_SCOPE_VIOLATION`), `ACTIVE` (otherwise `ERR_CLINICIAN_SUSPENDED`) and still credentialed (otherwise `ERR_CLINICIAN_CREDENTIAL_EXPIRED`).

A screened player may be returned to the field only under narrow conditions, and returning them takes the evaluation `SCREENED → CLEARED_ON_FIELD` with `diagnosis_outcome` set to `NO_CONCUSSION`, an optional `documentation_note` recorded by the physician, and the evaluation's `version` incremented by 1. All of the following must hold: `mandatory_removal` is false, the `no_go_signs` list is empty, `screen_symptom_score` is 0, and the game is still `IN_PROGRESS`. Any of the first three failing yields `ERR_MANDATORY_REMOVAL_ENFORCED`. Additionally, no other evaluation for the same player in the same game may be `DIAGNOSED` or `HELD_OUT_INCONCLUSIVE`; if one is, the on-field clearance is refused with `ERR_SAME_GAME_RETURN_PROHIBITED`. An on-field clearance leaves `availability_status` at `AVAILABLE` and re-derives the player's `public_injury_designation`; because no player field actually moves, the player row is not mutated at all and its `version` does not advance.

### 3.4. The Locker-Room Examination and Consultant Attendance

Where an on-field clearance is not available, the player goes to the locker room. A `ClubPhysician` takes the evaluation `SCREENED → LOCKER_ROOM_EXAM` by naming an `inc_clinician_id` — the clinician who will attend the examination. The server stamps `exam_started_at` from the logical clock and derives `inc_block_ends_at` at exactly 30 minutes later, then increments the evaluation's `version` by 1.

Who may attend is tightly constrained. The named clinician's `affiliation` must be `UNAFFILIATED_OBSERVER` or `INDEPENDENT_CONSULTANT`, and must not be the evaluation's own `evaluating_clinician_id`; a club-affiliated nominee, or the screening physician nominating themselves, is refused with `ERR_EXAM_INC_INELIGIBLE`. The nominee must additionally be `ACTIVE` and still credentialed, refused otherwise with `ERR_CLINICIAN_SUSPENDED` or `ERR_CLINICIAN_CREDENTIAL_EXPIRED` respectively — the nominee is checked here even though the nominee is not the caller. Note that an `UnaffiliatedObserver` may be *named* as the attending clinician but is never the caller of this operation.

A consultant cannot be in two locker rooms at once. The requested block runs from the logical clock's current instant through 30 minutes later, treated as a **closed** interval at both ends. Against it the server tests every other evaluation whose `inc_clinician_id` is the same consultant and whose `status` is `LOCKER_ROOM_EXAM`, `DIAGNOSED`, `NO_CONCUSSION_CLEARED` or `HELD_OUT_INCONCLUSIVE`, each contributing the closed interval from its `exam_started_at` to its `inc_block_ends_at`. If the requested block shares even a single instant with any of those, the request is refused with `ERR_INC_EXAM_WINDOW_CONFLICT` — touching endpoints do collide, so a request made at exactly the instant an earlier block ends is refused while one made a second later succeeds. Evaluations that never reached the locker room — those `INITIATED`, `SCREENED`, `CLEARED_ON_FIELD` or `PROTOCOL_BREACH` — hold no block at all.

Whatever the outcome, the examination must last long enough to be credible. The server computes `exam_duration_minutes` as the whole number of minutes between `exam_started_at` and `exam_completed_at`, discarding any part-minute remainder, and no conclusion of any kind may be recorded until that figure is at least 8. An earlier attempt is refused with `ERR_LOCKER_ROOM_EXAM_TOO_SHORT`.

Two of the three conclusions do not open a case, and they are declared with an `outcome` value together with an optional `documentation_note`. Declaring `NO_CONCUSSION` takes the evaluation `LOCKER_ROOM_EXAM → NO_CONCUSSION_CLEARED`, stamps `exam_completed_at` from the logical clock along with `exam_duration_minutes`, sets `diagnosis_outcome` to `NO_CONCUSSION`, creates no concussion case, leaves every player field untouched, and increments the evaluation's `version` by 1. That branch additionally requires the `no_go_signs` list recorded at the screen to be empty: a screen that saw any no-go sign forbids a no-concussion conclusion outright, refused with `ERR_NO_GO_SIGNS_PRESENT`, and the examination must instead end in a diagnosis or as inconclusive. Declaring `INCONCLUSIVE` takes the evaluation `LOCKER_ROOM_EXAM → HELD_OUT_INCONCLUSIVE`, stamps `exam_completed_at` and `diagnosis_outcome` `INCONCLUSIVE`, is permitted regardless of what the screen saw, and likewise increments the evaluation's `version` by 1; from that point the player may not be cleared on field for that game by any other evaluation, which surfaces as `ERR_SAME_GAME_RETURN_PROHIBITED`. Both branches require the evaluation to be `LOCKER_ROOM_EXAM` (otherwise `ERR_EVALUATION_STATE_INVALID`) and both are subject to the eight-minute minimum.

### 3.5. Diagnosis, Case Creation and Severity Assessment

The third conclusion is a diagnosis, and it is the point at which the protocol acquires a case. A `ClubPhysician` of the player's club documents it by supplying the `symptom_score` and `composite_score` measured during the examination, plus an optional `documentation_note`. The evaluation moves `LOCKER_ROOM_EXAM → DIAGNOSED`, with `exam_completed_at` stamped from the logical clock, `exam_duration_minutes` computed, and `diagnosis_outcome` set to `CONCUSSION`. A player may hold at most one case whose `case_status` is anything other than `CLEARED_FOR_CONTACT`, so diagnosing a player who already has an open case is refused with `ERR_OPEN_CASE_EXISTS`. Because the operation mints a case, it answers `201 Created` and the `data` it returns is the newly created concussion case, not the evaluation that produced it.

The new case copies `player_id` from the evaluation, denormalises `club_id` from the player's club at this instant and **never re-derives it afterwards**, records `sideline_evaluation_id` as the evaluation that produced it and `diagnosing_clinician_id` as the documenting physician, copies `season_year` from that evaluation's game, and stamps `diagnosis_at` from the logical clock together with `initial_symptom_score` and `diagnosis_composite_score` from the request. It opens with `case_status` `MANDATORY_REMOVAL`, `monitoring_status` `ACTIVE_SYMPTOM_WATCH`, `roster_exemption_status` `NONE`, `rtp_stage` 0 and `recurrence_count` 0. Where `initial_symptom_score` is at least 4, `last_symptomatic_at` is stamped equal to `diagnosis_at`; `last_symptom_check_score` remains null until a symptom check runs.

The case also links to the player's protocol history. `prior_case_id` is resolved as the same player's most recent earlier case within the same `season_year`, chosen by the greatest `diagnosis_at` and, where two share that instant, by the earlier `created_at`; it is null when the player has no earlier case that season.

**Severity** is then scored out of 100 by adding five components. The starting point is 40 points. The symptom term is the smaller of 30 and three times `initial_symptom_score`. The recurrence term is the smaller of 24 and twelve times `recurrence_count`. The history term is 10 points when `prior_case_id` is present and 0 when it is null. The baseline term needs `baseline_deviation_points` first: where the player had a baseline test with `status` `VALID` at the moment of diagnosis, that figure is the greater of 0 and the latest such test's `composite_score` minus `diagnosis_composite_score`; where the player had no `VALID` baseline at all, `baseline_deviation_points` is 0. The baseline term itself is a flat 15-point penalty when the player had no `VALID` baseline; otherwise it is the smaller of 15 and `baseline_deviation_points` multiplied by 1.5 and rounded half up — the rounding happens **before** the 15-point cap, never after. The five terms are summed, and `severity_index` is that sum bounded below at 0 and above at 100. A `severity_index` of at least 70 marks the case high-severity, which matters both to the return timeline and to fine pricing. The baseline snapshot used here is read once at diagnosis and never re-read; the severity score is recomputed only on a recurrence, and a recomputation reuses the same stamped `baseline_deviation_points`.

At the same time the server stamps `projected_return_at`, the **provisional projection** of when the player might come back: `diagnosis_at` plus seven days, plus a further three days when `severity_index` is at least 70. This figure is stamped exactly once and is never revised — not by recurrences, not by stage failures, not by anything. It is a publication figure and gates nothing at all. The gating figure is `earliest_return_at`, described in §3.6, which stays null until the player completes the ladder.

Diagnosis cascades into the player and the baseline register. The player's `availability_status` becomes `PROTOCOL_RESTRICTED`, `public_injury_designation` becomes `OUT`, and `diagnosed_case_count` increases by 1. The player's latest `VALID` baseline test has its `retest_required_reason` stamped `NEW_DIAGNOSIS`, which by the resolution rule of §3.2 drives `baseline_status` to `RETEST_REQUIRED`. Both the player's `version` and the evaluation's `version` increment by 1.

Finally, `heightened_review_required` is true on a case exactly while its owning club is on `PROBATION` or `SANCTIONED` and the case has not reached `CLEARED_FOR_CONTACT`. Its practical effect is a segregation-of-duties rule inside the club's own medical staff, described next.

### 3.6. Graduated Return to Participation

Return to participation runs up a five-rung ladder, each rung a separate record. A `ClubPhysician` of the case's club opens a rung by supplying its `stage_index`, and the value must be exactly one greater than the case's current `rtp_stage`; anything else — skipping ahead, or repeating a stage already passed — is refused with `ERR_STAGE_SEQUENCE_VIOLATION`. Only one rung may be live at a time: opening a stage while another step on the case is still `IN_PROGRESS` is refused with `ERR_STEP_ALREADY_IN_PROGRESS`. Opening the first rung takes the case `MANDATORY_REMOVAL → RTP_IN_PROGRESS`; opening rungs two through five leaves the case in `RTP_IN_PROGRESS`, and each opening increments the case's `version` by 1.

The `stage_name` is derived from the index rather than supplied: stage 1 is `SYMPTOM_LIMITED_ACTIVITY`, stage 2 is `AEROBIC_EXERCISE`, stage 3 is `SPORT_SPECIFIC_DRILLS`, stage 4 is `NON_CONTACT_TRAINING`, and stage 5 is `FULL_CONTACT_PRACTICE`. The server also derives `attempt_index` as one more than the number of earlier steps on the same case carrying the same `stage_index`, so a repeated stage is distinguishable from its first attempt. A new step opens with `status` `IN_PROGRESS`, `started_at` stamped from the logical clock, and `evaluated_at`, `cleared_by_clinician_id` and `evaluation_symptom_score` all still null.

Two independent time gates govern the ladder, and both are half-open, so adjacency is allowed at the boundary instant. The first is the **rest buffer** between rungs, recorded as `min_start_at`. For stage 1 there is no buffer and `min_start_at` equals the case's `diagnosis_at`. For stages 2, 3 and 4 the buffer is one day after the previous stage's sign-off; for stage 5 it is two days. Concretely, `min_start_at` is the `evaluated_at` of the case's passed step for the immediately preceding stage plus that buffer, and a request to open the stage before `min_start_at` is refused with `ERR_STAGE_REST_BUFFER_VIOLATION` while a request at exactly `min_start_at` succeeds. Only `PASSED`, non-`REVOKED` steps supply a rest anchor; a failed or revoked step never does.

The second gate is the **dwell** the player must spend inside the rung, recorded as `dwell_complete_at`. Stages 1, 2 and 3 each require one day; stages 4 and 5 each require two days. `dwell_complete_at` is the step's `started_at` plus that requirement, and a pass before it is refused with `ERR_STAGE_DWELL_NOT_MET` while a pass at exactly `dwell_complete_at` succeeds.

Signing a rung off is a `ClubPhysician` action carrying an `outcome` and the `symptom_score` observed at evaluation, which is recorded as `evaluation_symptom_score`. A symptom score of 4 or more is a **recurrence**; 3 or less is not. The two are not interchangeable: declaring `PASS` with a score of 4 or more, or declaring `SYMPTOM_RECURRENCE` with a score of 3 or less, is refused with `ERR_SYMPTOM_OUTCOME_MISMATCH`. Either outcome requires the step to be `IN_PROGRESS` (otherwise `ERR_STEP_STATE_INVALID`, which doubles as the guard against a second sign-off on the same step) and the case not to be `STAGE_FROZEN` (otherwise `ERR_CASE_STAGE_FROZEN`).

A `PASS` moves the step `IN_PROGRESS → PASSED`, stamps `evaluated_at` from the logical clock and `cleared_by_clinician_id` from the acting physician, and sets the case's `rtp_stage` to that step's `stage_index`. Where the case carries `heightened_review_required`, the signing physician must not be the case's `diagnosing_clinician_id`; the club's own diagnosing clinician signing off a stage under heightened review is refused with `ERR_HEIGHTENED_REVIEW_CLINICIAN_REQUIRED`. When the stage that passes is stage 5, the server computes the case's `earliest_return_at` — the **final accrued** return timeline — as that step's `evaluated_at` plus one day, plus a further two days for each recurrence the case has accumulated, using `recurrence_count` as it stands at the moment of that pass. Both the step's `version` and the case's `version` increment by 1. This is the accrued figure that actually gates return to contact, and it routinely differs from the provisional `projected_return_at` stamped back at diagnosis.

A `SYMPTOM_RECURRENCE` moves the step `IN_PROGRESS → FAILED_SYMPTOM_RECURRENCE`, likewise stamping `evaluated_at` and `cleared_by_clinician_id`, and it costs the player ground. The case's `recurrence_count` increases by 1, `last_symptomatic_at` is stamped from the logical clock, `rtp_stage` drops to the greater of 0 and that step's `stage_index` minus 2, `earliest_return_at` is cleared back to null, and `severity_index` is recomputed with the higher recurrence term. Where the resulting `recurrence_count` reaches 2 or more, `monitoring_status` moves `ACTIVE_SYMPTOM_WATCH → PROLONGED_SYMPTOM_WATCH`, which in turn forces the player's `availability_status` to `PROTOCOL_RESTRICTED` and `public_injury_designation` to `OUT`. The step's `version` and the case's `version` increment by 1, and the player's does too where the player was touched. One asymmetry is deliberate and load-bearing: the dwell requirement is **not** enforced on the recurrence branch, because a player who becomes symptomatic must be reportable immediately, at any point inside the rung.

### 3.7. Final Consultant Clearance and Return to Contact

Completing the ladder does not return a player to contact; only an independent consultant can. A `ClubPhysician` of the case's club requests that decision by naming an `inc_clinician_id` and supplying the `expected_case_version` required by §2.6. The case must have at least one return step — a case with none is refused with `ERR_NO_RETURN_STEPS_RECORDED` — and every stage from 1 through 5 must have a `PASSED`, non-`REVOKED` step, else the request is refused with `ERR_RTP_STAGES_INCOMPLETE`. The nominated consultant must be an `INDEPENDENT_CONSULTANT` whose `club_id` is null, must not be the case's `diagnosing_clinician_id`, and must not be the clinician who attended that case's locker-room examination; each of those failures is refused with `ERR_INC_NOT_INDEPENDENT`. The consultant must also be `ACTIVE` and credentialed, and the case's club must not be `SANCTIONED`.

A successful request first sets any clearance on the case still `PENDING` to `SUPERSEDED` — moving it `PENDING → SUPERSEDED` with `decided_at` left null — then creates the new clearance with `status` `PENDING`, `requested_at` stamped from the logical clock, `requested_by_clinician_id` taken from the acting physician, and `documented_stage_count` derived as the number of distinct `stage_index` values that have a `PASSED`, non-`REVOKED` step on the case at request time. The case moves `RTP_IN_PROGRESS → PENDING_INC_CLEARANCE` and its `version` increments by 1.

Only the assigned consultant may decide, and a decision by anyone else is refused with `ERR_INC_ASSIGNMENT_MISMATCH`. The decision carries a `decision` value and `decision_notes` recording the consultant's rationale — both required, `decision_notes` being a non-empty string — and requires the clearance to be `PENDING` (otherwise `ERR_CLEARANCE_STATE_INVALID`, which also guards against a second decision on the same clearance). The consultant must be `ACTIVE` and credentialed. Deciding a clearance is not one of the four writes the freeze guard of §2.5 rung 11 covers, so a club sanction never blocks a decision; but neither denial branch is gated on the case's own status either, and where a sanction has meanwhile left the case `STAGE_FROZEN` a denial still records its decision and still applies its ladder consequences while leaving `case_status` at `STAGE_FROZEN` rather than moving it to `RTP_IN_PROGRESS`. Three decisions are possible, and their consequences diverge sharply.

**`APPROVED`** moves the clearance `PENDING → APPROVED`, stamps `decided_at` from the logical clock, and sets `expires_at` to exactly seven days later. Approval requires the case to be `PENDING_INC_CLEARANCE` (otherwise `ERR_CASE_STATE_INVALID`) and requires every stage from 1 to 5 to *still* hold a `PASSED`, non-`REVOKED` step at decision time (otherwise `ERR_RTP_STAGES_INCOMPLETE`) — a stage revoked between request and decision blocks the approval. The case does **not** advance on approval: it stays `PENDING_INC_CLEARANCE` until the club physician actually returns the player to contact. The clearance's `version` increments by 1.

**`DENIED_MORE_REST`** moves the clearance `PENDING → DENIED_MORE_REST` with `decided_at` stamped, and pushes the player back down the ladder. The case's highest passed return step — selected by the greatest `stage_index`, then the greatest `attempt_index`, then the most recent `created_at` — moves `PASSED → REVOKED`, meaning that stage must be repeated as a new step with the next `attempt_index`. The case's `rtp_stage` drops to the greater of 0 and one less than its current value, `earliest_return_at` is cleared to null, and the case returns `PENDING_INC_CLEARANCE → RTP_IN_PROGRESS`. The revoked step's `version` and the case's `version` each increment by 1.

**`DENIED_INSUFFICIENT_DOCUMENTATION`** moves the clearance `PENDING → DENIED_INSUFFICIENT_DOCUMENTATION` with `decided_at` stamped, and diverges from the more-rest denial in precisely the way that matters: **no return step is revoked, `rtp_stage` is unchanged, and `earliest_return_at` is retained.** The case still returns `PENDING_INC_CLEARANCE → RTP_IN_PROGRESS`, and its `version` increments by 1, so the club may re-request clearance with better paperwork without repeating a stage.

An approval does not last forever. The operational sweep moves an `APPROVED` clearance `APPROVED → EXPIRED` at or after its `expires_at`, provided the case has not already reached `CLEARED_FOR_CONTACT`, incrementing the clearance's `version` by 1. The case remains `PENDING_INC_CLEARANCE`, and any subsequent attempt to return the player to contact then fails with `ERR_INC_CLEARANCE_EXPIRED`.

Returning to contact is the terminal act, performed by a `ClubPhysician` of the case's club with an optional `documentation_note` — validated as a string when present but not persisted anywhere on the case — and it takes the case `PENDING_INC_CLEARANCE → CLEARED_FOR_CONTACT`. Five conditions must hold. The club must not be `SANCTIONED`. The case's most recent clearance — the one with the greatest `requested_at`, ties broken by the later `created_at` and then by the later insertion order — must be `APPROVED`, else `ERR_INC_CLEARANCE_MISSING`, and its `expires_at` must be strictly later than the logical clock, else `ERR_INC_CLEARANCE_EXPIRED`. The logical clock must have reached `earliest_return_at`, else `ERR_RETURN_BEFORE_EARLIEST_DATE`; a case whose `earliest_return_at` is still null fails that same check with that same error. And the player's `baseline_status` must be `VALID` — a status of `RETEST_REQUIRED` is refused with `ERR_BASELINE_RETEST_REQUIRED` and a status of `NONE` with `ERR_BASELINE_NOT_ESTABLISHED`.

On success the server stamps `cleared_for_contact_at` from the logical clock and sets `heightened_review_required` to false. Where the case held a roster exemption, that exemption moves `GRANTED → RELEASED` as a compensating release: the club's `exemption_slots_used` decreases by 1 and `exemption_slots_available` increases by 1. The player's `availability_status` returns to `AVAILABLE` and `public_injury_designation` is re-derived, which under the rules of §3.9 typically means `QUESTIONABLE` for the following three days. The approving consultant's `cases_cleared_count` increases by 1, which refreshes that clinician's `updated_at` but deliberately does **not** advance the clinician's `version`. The case's `version` and the player's `version` each increment by 1, and the club's `version` increments too where a slot was released. The case's `frozen_from_status` is also reset to null on the way through.

### 3.8. Symptom Monitoring, Prolonged Watch and Roster Exemptions

A case tracks three state dimensions at once, and they move independently: `case_status` follows the protocol, `monitoring_status` follows the player's symptoms, and `roster_exemption_status` follows the club's roster accounting. A case in `CLEARED_FOR_CONTACT` may still be under active monitoring, and a frozen case still holds whatever exemption it held.

Symptom checks are the monitoring instrument, recorded by a `ClubPhysician` of the case's club with a `symptom_score`, and they are permitted against a case in **any** `case_status`, `CLEARED_FOR_CONTACT` included, because post-clearance and off-season surveillance is the point. Every check records `last_symptom_check_score`, and every check increments the case's `version` by 1.

A check reporting a score of 4 or more is a recurrence and behaves like a failed stage. It stamps `last_symptomatic_at` from the logical clock, increases `recurrence_count` by 1, and recomputes `severity_index`. Where the case was `PENDING_INC_CLEARANCE`, the check additionally denies the pending clearance as `DENIED_MORE_REST` with `decided_at` stamped from the logical clock, revokes the case's highest passed step by the same selection rule as a consultant's more-rest denial, drops `rtp_stage` to the greater of 0 and one less than its current value, clears `earliest_return_at` to null, and returns the case `PENDING_INC_CLEARANCE → RTP_IN_PROGRESS`. Where the resulting `recurrence_count` reaches 2 or more, `monitoring_status` moves `ACTIVE_SYMPTOM_WATCH → PROLONGED_SYMPTOM_WATCH` regardless of how few days have elapsed, and the player is driven to `PROTOCOL_RESTRICTED` and `OUT`.

The other trigger for prolonged watch is time. The server tracks `days_since_diagnosis` as the whole number of complete 24-hour periods between `diagnosis_at` and the logical clock, discarding any part-day remainder; it is derived afresh on every read of the case rather than stored, and it never goes negative — a clock wound back earlier than `diagnosis_at` reads 0. During a sweep, a case whose `days_since_diagnosis` has reached 21 and whose `case_status` is not `CLEARED_FOR_CONTACT` moves `ACTIVE_SYMPTOM_WATCH → PROLONGED_SYMPTOM_WATCH`; the twenty-first day exactly qualifies. That transition also forces `availability_status` to `PROTOCOL_RESTRICTED` and `public_injury_designation` to `OUT`, and increments the case's `version` by 1 — and the player's too, but only where that player's `availability_status` was not already `PROTOCOL_RESTRICTED`, since an unchanged player row is not mutated.

The off-season programme supersedes both. For a case whose `season_year` is a given year, the off-season begins at midnight UTC on 15 February of the following year. At or after that instant a sweep moves the case to `OFFSEASON_MONITORING` from either `ACTIVE_SYMPTOM_WATCH` or `PROLONGED_SYMPTOM_WATCH`, incrementing the case's `version` by 1 — and where both the off-season boundary and the 21-day line would fire in the same sweep, the off-season transition takes precedence, so the prolonged flag is simply superseded by the off-season programme.

Monitoring closes only one way. A symptom check reporting a score of exactly 0 against a case that is both `OFFSEASON_MONITORING` and `CLEARED_FOR_CONTACT` moves `monitoring_status` to the terminal `MONITORING_CLOSED`, records `last_symptom_check_score` as 0, and increments the case's `version` by 1.

Roster exemptions are the club's own accounting, and only the case's `ClubComplianceOfficer` may grant one — the acting officer's identifier must equal the case's `club_id`, else `ERR_CLUB_SCOPE_VIOLATION`. The grant request carries no body fields of its own and answers `200 OK` with the updated case. A grant moves the case `NONE → GRANTED`, requires the case's `roster_exemption_status` to be `NONE` (a case already `GRANTED` or `RELEASED` is refused with `ERR_EXEMPTION_ALREADY_GRANTED`), requires the case not to have reached `CLEARED_FOR_CONTACT` (otherwise `ERR_CASE_STATE_INVALID`), and requires the club to have at least one slot available (otherwise `ERR_NO_EXEMPTION_SLOTS`). The club's `exemption_slots_used` increases by 1 and `exemption_slots_available` decreases by 1, and both the case's and the club's `version` increment by 1. The only route out of `GRANTED` is the compensating release that fires when the case reaches `CLEARED_FOR_CONTACT`, described in §3.7.

### 3.9. League Injury Reporting and Public Designations

A player's `public_injury_designation` is not filed by the club — it is resolved by the league from the player's cases, and the club's filing must agree with it. Resolution takes the **first matching rule** in this exact order:

1. `OUT` when the player has any case whose `case_status` is `MANDATORY_REMOVAL`, `RTP_IN_PROGRESS`, `PENDING_INC_CLEARANCE` or `STAGE_FROZEN`, or any case whose `monitoring_status` is `PROLONGED_SYMPTOM_WATCH`.
2. `DOUBTFUL` when the player's most recent case by `diagnosis_at` — ties broken by the later `created_at` and then by the later insertion order — is `CLEARED_FOR_CONTACT` with a non-null `cleared_for_contact_at`, the logical clock is still strictly earlier than 72 hours after that instant, and that case's `recurrence_count` is at least 1.
3. `QUESTIONABLE` when the same 72-hour window still applies and that case's `recurrence_count` is 0.
4. `NONE` otherwise.

The post-clearance window is half-open: at exactly 72 hours after `cleared_for_contact_at` the window has closed and the designation falls to `NONE`. Sideline evaluations never influence the designation; only cases do. The designation is recomputed on every write that touches any of the player's cases.

Filing is the `ClubComplianceOfficer`'s duty and is scoped to the officer's own club. Each entry names a `game_id` and a `player_id`, declares the player's `practice_participation` as `DNP`, `LIMITED` or `FULL`, and declares a `designation`. The server copies `club_id` from the player at filing time, stamps `filed_at` from the logical clock, and stamps `required_designation` as the league-resolved value described above. The filed `designation` must equal that `required_designation`, and a mismatch is refused with `ERR_INJURY_DESIGNATION_MISMATCH`. The player's club must be the home or away club of the referenced game, else `ERR_PLAYER_CLUB_MISMATCH`, and at most one entry may exist for any pairing of game and player, a second attempt being refused with `ERR_DUPLICATE_INJURY_REPORT`.

Timing decides the entry's `status`. The window opens four days before `kickoff_at` and the late line falls ninety minutes before it. A filing earlier than the opening instant is refused with `ERR_REPORT_WINDOW_NOT_OPEN`. A filing at or after the opening instant but strictly before the late line is stamped `FILED`. A filing at or after the late line but strictly before `kickoff_at` is stamped `LATE_FILED`, and it costs the club: the server opens an audit against the club on its own initiative with `auto_opened` true, `opened_by_user_id` null, a `case_id` of null, `violation_codes` of exactly `[LATE_INJURY_REPORT]` and `exposure_days` of 0, advances it straight to `FINDINGS_ISSUED` — stamping `escalation_tier_at_issuance` and computing `assessed_fine_cents` as §3.10 describes — and then re-derives the club's whole posture through the seven-step routine of §2.8. Such an audit is minted already in `FINDINGS_ISSUED` rather than transitioned into it, so it is born at `version` 1 with `updated_at` equal to `created_at`, with `findings_issued_at` set to the logical clock and both `findings_issued_by_user_id` and `sideline_evaluation_id` null; and because the server is issuing on its own initiative, the season fine cap of §2.8 is not applied to it and `ERR_CLUB_FINE_CAP_EXCEEDED` can never be raised by a filing. A filing at or after `kickoff_at` is refused with `ERR_REPORT_WINDOW_CLOSED`.

An entry may be amended while it is `FILED` or `LATE_FILED`, moving it to the terminal `AMENDED`; amending an entry that is already `AMENDED` is refused with `ERR_RESOURCE_STATE_INVALID`. The amendment supplies a fresh `practice_participation` and `designation`, must arrive strictly before `kickoff_at` (otherwise `ERR_REPORT_WINDOW_CLOSED`), and its new `designation` must equal the freshly recomputed `required_designation` (otherwise `ERR_INJURY_DESIGNATION_MISMATCH`). On success the server stamps `amended_at` from the logical clock, records the outgoing value as `amended_from_designation`, overwrites `designation` and `required_designation` with the new values, and increments the entry's `version` by 1. Both `amended_at` and `amended_from_designation` are null until the first amendment. An amendment does **not** withdraw a late-filing audit already issued at filing time — the late filing happened, and the penalty stands.

### 3.10. Protocol Auditing, Penalty Pricing and Club Sanctions

Auditing is where the league prices protocol failures, and it is deliberately split across three distinct auditor identities. A `LeagueAuditor` opens an audit against a `club_id`, optionally naming the `case_id` under audit and optionally the `sideline_evaluation_id` under audit; both are null for a reporting-only audit, and `case_id` is null for an evaluation-only one. The new audit opens with `status` `OPEN`, `auto_opened` false, `opened_by_user_id` set to the opening auditor's opaque identifier, `disposition` `PENDING`, `assessed_fine_cents` 0, `response_round_count` 0 and an empty `violation_codes` array, and it raises the club's `open_violation_count` by 1 and the club's `version` by 1. Fields not yet applicable are null: `escalation_tier_at_issuance`, `club_response_note`, `findings_issued_by_user_id`, `closed_by_user_id`, `closing_note`, `findings_issued_at` and `closed_at`.

Issuing findings prices the audit, and a **different** auditor must do it: an auditor whose identifier equals `opened_by_user_id` issuing findings is refused with `ERR_SEGREGATION_OF_DUTIES`. The request supplies `violation_codes`, a non-empty selection from `UNAUTHORIZED_SAME_GAME_RETURN`, `MISSING_INC_CLEARANCE`, `MISSED_MANDATORY_REMOVAL`, `EVALUATION_DEADLINE_BREACH`, `INCOMPLETE_LOCKER_ROOM_EXAM`, `BASELINE_TEST_MISSING` and `LATE_INJURY_REPORT`, together with `exposure_days` — the number of days the violation persisted, from 0 to 30 inclusive. Findings may be issued from `OPEN`, taking the audit `OPEN → FINDINGS_ISSUED`, or re-issued from `CLUB_RESPONDED`, taking it `CLUB_RESPONDED → FINDINGS_ISSUED` as a revision; from any other status the request is refused with `ERR_AUDIT_STATE_INVALID`.

The steps are pinned and must run in this order.

1. Stamp `escalation_tier_at_issuance` as the tier band of the club's preliminary compliance score **recomputed with this audit excluded** from the included set. For an audit still `OPEN` that is simply the club's live `escalation_tier`; for a `CLUB_RESPONDED` audit being revised, excluding it prevents the audit from pricing itself.
2. Store the supplied `violation_codes` and `exposure_days`, replacing whatever the audit carried before.
3. Compute `assessed_fine_cents` using the stamped tier.
4. Set `status` to `FINDINGS_ISSUED`, `findings_issued_at` to the logical clock, and `findings_issued_by_user_id` to the acting auditor's identifier.
5. Re-derive the club's whole posture through the seven-step routine of §2.8.

The fine itself is built from three factors and rounded twice. The **exposure factor** is 7 plus `exposure_days`, all divided by 7, held as an exact rational and never pre-rounded. The **severity factor** is 1.15 when the audit names a `case_id` whose case has a `severity_index` of at least 70, and 1.00 in every other situation — including every audit with a null `case_id`. Then, walking the codes present on the audit in the canonical order `UNAUTHORIZED_SAME_GAME_RETURN`, `MISSING_INC_CLEARANCE`, `MISSED_MANDATORY_REMOVAL`, `EVALUATION_DEADLINE_BREACH`, `INCOMPLETE_LOCKER_ROOM_EXAM`, `BASELINE_TEST_MISSING`, `LATE_INJURY_REPORT` — regardless of the order the request listed them in — each code contributes one line: its base amount multiplied by the exposure factor and then by the severity factor, that product rounded half up to a whole cent. The base amounts in cents are 25000000 for `UNAUTHORIZED_SAME_GAME_RETURN`, 20000000 for `MISSING_INC_CLEARANCE`, 15000000 for `MISSED_MANDATORY_REMOVAL`, 5000000 for `EVALUATION_DEADLINE_BREACH`, 7500000 for `INCOMPLETE_LOCKER_ROOM_EXAM`, 2500000 for `BASELINE_TEST_MISSING` and 1500000 for `LATE_INJURY_REPORT`. The rounded lines are summed to a gross figure, and `assessed_fine_cents` is that gross figure multiplied by the tier multiplier of the **stamped** `escalation_tier_at_issuance` — 1.00 for `TIER_0`, 1.50 for `TIER_1`, 2.00 for `TIER_2`, 3.00 for `TIER_3` — rounded half up once more. Rounding per line and then summing is normative; summing unrounded lines and rounding once at the end yields a different figure and is wrong. Using the club's live tier after the posture routine has run, instead of the stamped tier, is likewise wrong.

Before the findings land, the server checks that the club's resulting `outstanding_fine_cents` would not exceed the season cap of 150000000 cents; findings that would breach it are refused with `ERR_CLUB_FINE_CAP_EXCEEDED`. On success the audit's `version` and the club's `version` each increment by 1, along with the `version` of every case the posture routine froze.

A club answers through its `ClubComplianceOfficer`, whose identifier must equal the audit's `club_id`. A response supplies a `response_note`, requires the audit to be `FINDINGS_ISSUED` (otherwise `ERR_AUDIT_STATE_INVALID`), and takes it `FINDINGS_ISSUED → CLUB_RESPONDED` while recording the note as `club_response_note` and increasing `response_round_count` by 1. A club may respond at most twice to one audit; a third attempt is refused with `ERR_AUDIT_RESPONSE_ROUNDS_EXHAUSTED`. Responding changes no compliance arithmetic whatsoever: a `CLUB_RESPONDED` audit remains inside the preliminary score's included set, so `compliance_score` and `outstanding_fine_cents` are exactly what they were. Only the audit's `version` increments.

Closing an audit adjudicates it, supplies a `disposition` and an optional `closing_note`, and is again reserved for a different auditor: an auditor whose identifier equals `findings_issued_by_user_id` closing the audit is refused with `ERR_SEGREGATION_OF_DUTIES`, and that comparison is skipped whenever `findings_issued_by_user_id` is null, as it is for auto-issued findings. A close is permitted from `OPEN`, `FINDINGS_ISSUED` or `CLUB_RESPONDED`; from any other status, `ERR_AUDIT_STATE_INVALID`.

A disposition of `UPHELD` takes the audit `FINDINGS_ISSUED → CLOSED_UPHELD` or `CLUB_RESPONDED → CLOSED_UPHELD` — the arithmetic is identical on both edges, and the club having responded changes nothing. The server sets `disposition` to `UPHELD`, stamps `closed_at` from the logical clock and `closed_by_user_id` from the acting auditor, and re-derives the club's posture. Because `CLOSED_UPHELD` sits inside both included sets, `compliance_score` and `outstanding_fine_cents` do not move; what changes is that `adjudicated_compliance_score` now drops to absorb the audit's weights and `open_violation_count` falls by 1. An audit still `OPEN`, with no findings ever issued, may **not** be upheld: that request is refused with `ERR_AUDIT_STATE_INVALID`.

A disposition of `DISMISSED` is a compensation, and it works identically from all three permitted from-states — `FINDINGS_ISSUED → CLOSED_DISMISSED`, `CLUB_RESPONDED → CLOSED_DISMISSED`, and `OPEN → CLOSED_DISMISSED`. The server sets `status` to `CLOSED_DISMISSED`, `disposition` to `DISMISSED`, resets `assessed_fine_cents` to 0, stamps `closed_at` and `closed_by_user_id`, and re-derives the club's posture. Because the audit now leaves both included sets, `compliance_score` and `outstanding_fine_cents` return to the values they held before the findings were issued, `escalation_tier` and the club's `status` are re-derived from the restored score, and any case that the sanction had frozen is restored to its recorded `frozen_from_status`. Dismissing an audit that was still `OPEN` changes no club figures at all — an `OPEN` audit never entered either compliance set — and only `open_violation_count` falls. The audit's `version` and the club's `version` increment by 1, along with the `version` of every case restored.

Club posture is what reaches the medical workflow. When the recomputed `compliance_score` lands between 70 and 89 inclusive the club becomes `PROBATION`, whether it was previously `ACTIVE` or `SANCTIONED`, and every case of that club not yet `CLEARED_FOR_CONTACT` gains `heightened_review_required`. When the recomputed score falls below 70 the club becomes `SANCTIONED`, from either `ACTIVE` or `PROBATION`, and every case of that club in `RTP_IN_PROGRESS` or `PENDING_INC_CLEARANCE` is frozen: `frozen_from_status` records the case's status as it stood and `case_status` becomes `STAGE_FROZEN`, with `heightened_review_required` true. A case that was `PENDING_INC_CLEARANCE` when frozen keeps any `PENDING` clearance intact — the clearance is not superseded by the freeze. While a case is `STAGE_FROZEN`, or while its club is `SANCTIONED`, the four return-to-participation writes — opening a stage, evaluating a stage, requesting final clearance, and returning to contact — are all refused with `ERR_CASE_STAGE_FROZEN`.

Restoration is the mirror image. When a dismissal lifts the recomputed score back into the 70-to-89 band the club moves `SANCTIONED → PROBATION`, every `STAGE_FROZEN` case is restored to its `frozen_from_status` with `frozen_from_status` cleared to null, and `heightened_review_required` stays true. When the score returns to 90 or above the club moves `SANCTIONED → ACTIVE` or `PROBATION → ACTIVE`, frozen cases are restored the same way, and `heightened_review_required` becomes false across the club's cases.

### 3.11. The Operational Sweep

Deadlines, expiries and calendar boundaries do not fire on their own; a `LeagueAdmin` advances them by running the operational sweep, which is the only way clock-driven state moves. The sweep processes in a **pinned order**, and inside each group it walks rows in ascending `created_at` order so that the outcome is deterministic:

1. **Evaluation breaches.** Every sideline evaluation whose `protocol_deadline_at` the logical clock has reached is breached. An evaluation in `INITIATED` moves `INITIATED → PROTOCOL_BREACH`, and one in `SCREENED` moves `SCREENED → PROTOCOL_BREACH`; in both cases the server opens an audit on its own initiative with `auto_opened` true, `opened_by_user_id` null, `club_id` taken from the player's club, `sideline_evaluation_id` set to the breached evaluation, `violation_codes` of exactly `[EVALUATION_DEADLINE_BREACH]` and `exposure_days` of 0, then immediately advances that audit to `FINDINGS_ISSUED`, stamping `escalation_tier_at_issuance` and computing `assessed_fine_cents` exactly as §3.10 prescribes, and finally re-derives the club's posture. An evaluation caught in `LOCKER_ROOM_EXAM` moves `LOCKER_ROOM_EXAM → PROTOCOL_BREACH` the same way, except that its auto-opened audit carries **two** codes — `[EVALUATION_DEADLINE_BREACH, INCOMPLETE_LOCKER_ROOM_EXAM]` — because the examination was left unconcluded.
2. **Baseline expiry.** Every baseline test whose `validity_expires_at` the clock has reached moves `VALID → EXPIRED` with `retest_required_reason` `SEASON_ROLLOVER`, and each affected player's `baseline_status` is re-resolved.
3. **Clearance expiry.** Every `APPROVED` consultant clearance whose `expires_at` the clock has reached, and whose case has not reached `CLEARED_FOR_CONTACT`, moves `APPROVED → EXPIRED`.
4. **Monitoring advance.** Cases cross the 21-day prolonged-symptom line or the off-season boundary as §3.8 describes, with the off-season programme taking precedence over the 21-day rule inside the same sweep.
5. **Club posture.** For every club touched in step 1, the seven-step posture routine of §2.8 runs, so case freezing and case restoration happen last.

Every row the sweep mutates has its `version` incremented by 1; an audit the sweep opens is created rather than mutated, so it too is born already in `FINDINGS_ISSUED` at `version` 1, with a null `findings_issued_by_user_id` and a null `case_id`, and outside the reach of the season fine cap. The sweep reports what it did through a summary object — returned at `200 OK` with `response_type` `object` — carrying `swept_at`, which is the logical clock's current instant, `breached_evaluation_ids`, `auto_opened_audit_ids`, `expired_baseline_test_ids`, `expired_inc_clearance_ids`, `prolonged_watch_case_ids`, `offseason_monitoring_case_ids`, `frozen_case_ids` and `restored_case_ids`. A second sweep run at the same logical clock value mutates nothing further.

## 4. Endpoint Definitions

Operations that mint a new resource return `201 Created`; operations that modify an existing resource, drive a state transition on it, or return a computed projection return `200 OK`. In the table below, "All roles" means all six roles named in §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/concussion-program/clubs` | Register a club | LeagueAdmin |
| GET | `/concussion-program/clubs/{id}` | Get a club | All roles |
| GET | `/concussion-program/clubs/{id}/players` | List a club's players | All roles |
| GET | `/concussion-program/clubs/{id}/compliance-summary` | Get a club's computed compliance summary | LeagueAdmin, LeagueAuditor, ClubComplianceOfficer |
| POST | `/concussion-program/clinicians` | Register a clinician | LeagueAdmin |
| POST | `/concussion-program/clinicians/{id}/suspend` | Suspend a clinician and cascade pending clearances | LeagueAdmin |
| GET | `/concussion-program/clinicians/{id}` | Get a clinician | All roles |
| GET | `/concussion-program/clinicians` | List clinicians | All roles |
| POST | `/concussion-program/players` | Register a player | LeagueAdmin, ClubComplianceOfficer |
| GET | `/concussion-program/players/{id}` | Get a player | All roles |
| GET | `/concussion-program/players` | List players | All roles |
| POST | `/concussion-program/games` | Schedule a game | LeagueAdmin |
| POST | `/concussion-program/games/{id}/advance-status` | Advance a game's lifecycle one step | LeagueAdmin |
| GET | `/concussion-program/games/{id}` | Get a game | All roles |
| GET | `/concussion-program/games` | List games | All roles |
| POST | `/concussion-program/baseline-tests` | File a baseline neurocognitive test | ClubPhysician |
| POST | `/concussion-program/baseline-tests/{id}/invalidate` | Administratively invalidate a baseline test | LeagueAdmin |
| GET | `/concussion-program/baseline-tests/{id}` | Get a baseline test | All roles |
| GET | `/concussion-program/baseline-tests` | List baseline tests | All roles |
| POST | `/concussion-program/sideline-evaluations` | Initiate a sideline evaluation | ClubPhysician, UnaffiliatedObserver |
| POST | `/concussion-program/sideline-evaluations/{id}/screen` | Record the sideline screen | ClubPhysician |
| POST | `/concussion-program/sideline-evaluations/{id}/locker-room-exam` | Begin the locker-room examination with an attending consultant | ClubPhysician |
| POST | `/concussion-program/sideline-evaluations/{id}/diagnose-concussion` | Document a concussion diagnosis and open a case | ClubPhysician |
| POST | `/concussion-program/sideline-evaluations/{id}/conclude-no-concussion` | Conclude the examination as no-concussion or inconclusive | ClubPhysician |
| POST | `/concussion-program/sideline-evaluations/{id}/clear-to-return` | Clear the player to return on field | ClubPhysician |
| GET | `/concussion-program/sideline-evaluations/{id}` | Get a sideline evaluation | All roles |
| GET | `/concussion-program/sideline-evaluations` | List sideline evaluations | All roles |
| POST | `/concussion-program/concussion-cases/{id}/return-steps` | Open the next graduated return stage | ClubPhysician |
| POST | `/concussion-program/concussion-cases/{id}/inc-clearances` | Request independent consultant final clearance | ClubPhysician |
| POST | `/concussion-program/concussion-cases/{id}/return-to-contact` | Return the player to contact | ClubPhysician |
| POST | `/concussion-program/concussion-cases/{id}/roster-exemption` | Grant a roster concussion exemption | ClubComplianceOfficer |
| POST | `/concussion-program/concussion-cases/{id}/symptom-check` | Record a monitoring symptom check | ClubPhysician |
| GET | `/concussion-program/concussion-cases/{id}` | Get a concussion case | All roles |
| GET | `/concussion-program/concussion-cases` | List concussion cases | All roles |
| POST | `/concussion-program/return-steps/{id}/evaluate` | Sign off or fail a return stage | ClubPhysician |
| GET | `/concussion-program/return-steps/{id}` | Get a return step | All roles |
| GET | `/concussion-program/return-steps` | List return steps | All roles |
| POST | `/concussion-program/inc-clearances/{id}/decide` | Decide a consultant clearance | IndependentConsultant |
| GET | `/concussion-program/inc-clearances/{id}` | Get a consultant clearance | All roles |
| GET | `/concussion-program/inc-clearances` | List consultant clearances | All roles |
| POST | `/concussion-program/protocol-audits` | Open a protocol audit | LeagueAuditor |
| POST | `/concussion-program/protocol-audits/{id}/findings` | Issue or revise audit findings and price the fine | LeagueAuditor |
| POST | `/concussion-program/protocol-audits/{id}/respond` | File a club response to audit findings | ClubComplianceOfficer |
| POST | `/concussion-program/protocol-audits/{id}/close` | Close an audit as upheld or dismissed | LeagueAuditor |
| GET | `/concussion-program/protocol-audits/{id}` | Get a protocol audit | All roles |
| GET | `/concussion-program/protocol-audits` | List protocol audits | All roles |
| POST | `/concussion-program/injury-report-entries` | File a league injury report entry | ClubComplianceOfficer |
| POST | `/concussion-program/injury-report-entries/{id}/amend` | Amend a league injury report entry | ClubComplianceOfficer |
| GET | `/concussion-program/injury-report-entries/{id}` | Get an injury report entry | All roles |
| GET | `/concussion-program/injury-report-entries` | List injury report entries | All roles |
| POST | `/concussion-program/protocol-sweeps` | Run the operational sweep | LeagueAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock | LeagueAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_ROLE_IDENTITY_MISMATCH` | 403 |
| `ERR_CLUB_SCOPE_VIOLATION` | 403 |
| `ERR_CLUB_NOT_FOUND` | 404 |
| `ERR_PLAYER_NOT_FOUND` | 404 |
| `ERR_CLINICIAN_NOT_FOUND` | 404 |
| `ERR_GAME_NOT_FOUND` | 404 |
| `ERR_EVALUATION_NOT_FOUND` | 404 |
| `ERR_CASE_NOT_FOUND` | 404 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_RESOURCE_STATE_INVALID` | 409 |
| `ERR_EVALUATION_STATE_INVALID` | 409 |
| `ERR_CASE_STATE_INVALID` | 409 |
| `ERR_STEP_STATE_INVALID` | 409 |
| `ERR_CLEARANCE_STATE_INVALID` | 409 |
| `ERR_AUDIT_STATE_INVALID` | 409 |
| `ERR_CLINICIAN_SUSPENDED` | 409 |
| `ERR_CASE_STAGE_FROZEN` | 409 |
| `ERR_STALE_PLAYER_VERSION` | 412 |
| `ERR_STALE_CASE_VERSION` | 412 |
| `ERR_MANDATORY_REMOVAL_ENFORCED` | 409 |
| `ERR_SAME_GAME_RETURN_PROHIBITED` | 409 |
| `ERR_NO_GO_SIGNS_PRESENT` | 409 |
| `ERR_LOCKER_ROOM_EXAM_TOO_SHORT` | 409 |
| `ERR_HEIGHTENED_REVIEW_CLINICIAN_REQUIRED` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INC_NOT_INDEPENDENT` | 422 |
| `ERR_EXAM_INC_INELIGIBLE` | 422 |
| `ERR_INC_ASSIGNMENT_MISMATCH` | 403 |
| `ERR_PLAYER_CLUB_MISMATCH` | 422 |
| `ERR_CLINICIAN_CREDENTIAL_EXPIRED` | 422 |
| `ERR_GAME_NOT_IN_PROGRESS` | 409 |
| `ERR_INC_EXAM_WINDOW_CONFLICT` | 409 |
| `ERR_STAGE_REST_BUFFER_VIOLATION` | 409 |
| `ERR_STAGE_DWELL_NOT_MET` | 409 |
| `ERR_RETURN_BEFORE_EARLIEST_DATE` | 409 |
| `ERR_INC_CLEARANCE_EXPIRED` | 409 |
| `ERR_REPORT_WINDOW_NOT_OPEN` | 409 |
| `ERR_REPORT_WINDOW_CLOSED` | 409 |
| `ERR_STAGE_SEQUENCE_VIOLATION` | 422 |
| `ERR_STEP_ALREADY_IN_PROGRESS` | 409 |
| `ERR_NO_RETURN_STEPS_RECORDED` | 422 |
| `ERR_RTP_STAGES_INCOMPLETE` | 422 |
| `ERR_INC_CLEARANCE_MISSING` | 409 |
| `ERR_BASELINE_NOT_ESTABLISHED` | 422 |
| `ERR_BASELINE_RETEST_REQUIRED` | 422 |
| `ERR_OPEN_CASE_EXISTS` | 409 |
| `ERR_SYMPTOM_OUTCOME_MISMATCH` | 422 |
| `ERR_INJURY_DESIGNATION_MISMATCH` | 422 |
| `ERR_DUPLICATE_INJURY_REPORT` | 409 |
| `ERR_AUDIT_RESPONSE_ROUNDS_EXHAUSTED` | 409 |
| `ERR_EXEMPTION_ALREADY_GRANTED` | 409 |
| `ERR_UNIQUENESS_VIOLATION` | 409 |
| `ERR_NO_EXEMPTION_SLOTS` | 409 |
| `ERR_CLUB_FINE_CAP_EXCEEDED` | 409 |
