# Neighborhood Watch Community Safety API — Product Requirements Document

## 1. Introduction

Police departments that sponsor neighborhood watch programs face a persistent coordination problem: volunteer groups form, drift, and regroup across dozens of blocks, while the department must decide which groups have earned program certification, which incident reports are credible enough to act on, and which groups may responsibly receive sensitive liaison data. Today this is tracked in spreadsheets and email threads, and the consequences show up as lapsed certifications, untrained captains fielding alerts, and incident patterns that surface only after a string of related reports.

This document specifies the Neighborhood Watch Community Safety API, the system of record for a police-sponsored watch program. The API governs the full program lifecycle: registering blocks under a watch group and appointing captains, maintaining the member contact roster and distributing alerts, taking incident reports through a segregated review pipeline that feeds block-level pattern mapping, chairing liaison meetings and executing data-sharing agreements, delivering bias-avoidance training, coordinating community events such as National Night Out, and scoring each group's participation and certification standing. Because volunteers, coordinators, and sworn officers all act on the same data, the system leans hard on derived state — a group's operational posture, its certification standing, and its participation metrics are computed from what actually happened — and on segregation of duties, so that no person reviews their own report and no officer certifies a group they themselves trained.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. The API is mounted under `/watch`.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes four roles, spelled exactly as follows: `ProgramCoordinator`, `LiaisonOfficer`, `BlockCaptain`, and `Member`. A request whose headers are missing or malformed, or whose declared role is not one of these four, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not permitted to invoke the endpoint per the authorization matrix in §4 is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `ProgramCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity profile; the server may record it as the actor of an administrative action, and segregation-of-duties rules may compare the raw identifier against a member id (for example, the reporter of an incident) to bar self-review, but no coordinator profile resource exists. When `X-User-Role` is `LiaisonOfficer`, `X-User-ID` is the `id` of the acting `LiaisonOfficer`; ownership checks on any resource that references a `LiaisonOfficer` compare the resource's foreign-key field — `liaison_officer_id`, `trainer_officer_id`, or `reviewing_officer_id` — to `X-User-ID`. When `X-User-Role` is `BlockCaptain` or `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's foreign-key field — such as `reporter_member_id` or the `member_id` supplied to an acknowledgement — to `X-User-ID`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — watch groups, blocks, members, captain assignments, incident reports, alerts, liaison meetings, liaison officers, data-sharing agreements, training sessions, community events, and certification reviews — carries a standard set of system-managed fields:

- `id` (string): A unique, server-generated identifier for the resource, formatted as a UUID with no type prefix.
- `created_at` (string): An ISO 8601 timestamp in UTC with three fractional digits (for example, `2026-08-01T12:00:00.000Z`) indicating when the resource was first created.
- `updated_at` (string): An ISO 8601 UTC timestamp with three fractional digits indicating when the resource was last modified. This field is refreshed upon any change to the resource's properties, including recomputation of derived fields.
- `version` (integer): A system-managed integer that increments by one with every modification to the resource. Certain write endpoints consume this field for optimistic concurrency control (see §2.7).

A mutation that cascades into a parent resource — for example, a block registration that recomputes the parent group's posture — independently updates the parent's `updated_at` and increments its `version`, so a client watching the parent can observe every cascade.

### 2.5. The Program Logical Clock

All temporal reasoning in the system — incident ages, quiet hours, meeting slots, agreement expiry, training cooldowns, event windows — runs against a single server-maintained **logical clock**, never against wall-clock time. Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it must never fall back to wall-clock time on its own. A `ProgramCoordinator` advances the clock through a test-driving capability that accepts a `to_iso8601` timestamp and answers with the resulting `current_utc`.

The logical clock interacts with data-sharing agreements lazily: an agreement whose `expires_at` has been reached or passed is not rewritten by a background job. Instead, the system checks the clock against `expires_at` on every read or write that touches the agreement — fetching or listing agreements, fetching a watch group covered by one, fetching an incident report governed by one — and transitions the agreement from `ACTIVE` to `EXPIRED` at that moment, with the same visibility and heat-map consequences as an explicit revocation. Setting the clock forward arms that sweep for the next access.

### 2.6. Request Validation Order and Nested Path Resolution

When several rules could reject the same request, the server evaluates them in a fixed priority order so that the surfaced error is deterministic. The order is: first, authentication of the `X-User-ID` and `X-User-Role` headers (`ERR_UNAUTHENTICATED`); second, role authorization against the endpoint (`ERR_UNAUTHORIZED`); third, existence of the resources named in the path (`ERR_NOT_FOUND`); fourth, whether the target resource is in a state from which the requested transition exists (`ERR_INVALID_STATE`); fifth, the watch-group posture gate (`ERR_POSTURE_GATED`); sixth, segregation of duties (`ERR_SEGREGATION_OF_DUTIES`); seventh, the temporal rules, in the order quiet hours (`ERR_QUIET_HOURS`), meeting room-slot conflict (`ERR_ROOM_SLOT_CONFLICT`), street-closure conflict (`ERR_CLOSURE_CONFLICT`), and training cooldown (`ERR_TRAINING_COOLDOWN`); then referential integrity across linked resources (`ERR_REFERENTIAL_INTEGRITY`); then block-captain coverage for block-scoped alerts (`ERR_NO_ACTIVE_CAPTAIN`); then uniqueness and cardinality (`ERR_CONSTRAINT_VIOLATION`); then the duplicate-open-review check (`ERR_DUPLICATE`); then field-level request validity (`ERR_INVALID_REQUEST`); then materials-inventory conservation (`ERR_INVENTORY_LIMIT`); then the data-sharing gate (`ERR_DATA_SHARE_REQUIRED`); then the certification gate (`ERR_CERTIFICATION_REQUIRED`); and finally the reporter-only resubmission check (`ERR_REPORTER_ONLY`). Because authentication and authorization precede everything, a caller without access never learns which later rule would have fired; because state and posture precede the business rules, a stale or gated request never reaches them.

For nested paths, existence validation proceeds strictly left to right: each path identifier is resolved in turn, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource, before any later segment is examined. A request addressed to a block under a non-existent watch group therefore fails on the group, and a request addressed to a child of a non-existent block fails on the block.

### 2.7. Optimistic Concurrency Control

Two creation flows are guarded by optimistic concurrency control on a parent resource's `version`, because in each case the product semantics allow the new resource to legitimately coexist with prior siblings, so no state precondition can catch a stale view of the parent.

Creating an alert — `POST /watch/alerts` — requires a non-optional `expected_watch_group_version` field carrying the client's last observed `version` of the parent watch group. If the group's current `version` does not match, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from drafting against a group state it has not observed.

Appointing a block captain — `POST /watch/blocks/{id}/captain-assignments` — requires a non-optional `expected_block_version` field carrying the client's last observed `version` of the parent block. A new active assignment supersedes any prior active one, so a sequential second create sees no state field that would reject it; the OCC check on the block's `version` is the sanctioned resolution, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not listed above do not take a version field, and no other endpoint participates in optimistic concurrency control.

### 2.8. Derived Posture and Hierarchical Reconciliation

A watch group's `posture` is a derived axis, never set directly: the server recomputes it whenever the underlying facts change — a block registers, a captain is appointed, relieved, or revoked, a member is suspended or withdraws, training is completed, certification changes, a freeze or unfreeze is issued. Posture gates what the group's children may do, so a single local change can ripple outward: a member suspension that revokes the only captain of a registered block drags the group from `OPERATIONAL` to `DEGRADED`, which in turn holds every queued alert of the group until coverage is restored. Each reconciliation that changes the parent group refreshes its `updated_at` and increments its `version`. The increment is exactly one per reconciliation, even when a single reconciliation changes several derived fields on the group at once — a triggering mutation that moves the group's posture and its participation score in the same pass raises the group's `version` once in total, not once per changed field. The cascades described in §3 always run to completion within the triggering request — the consistency model is immediate, with no deferred settlement.

Conversely, operations on children validate the parent first: where a group-level gate applies (posture, certification), the gate is evaluated before the child-specific rule, per the ordering in §2.6.

### 2.9. Numeric Precision and Rounding

Different metrics use different precision disciplines, and the discipline is part of the contract. The participation score and the certification-points composite use pure integer arithmetic: every weight is an integer, and no fractional rounding occurs anywhere in their evaluation. The block risk-heat score uses decimal arithmetic with per-term rounding: each incident's contribution is rounded half-up to exactly 2 decimal places before the contributions are summed. The alert fan-out uses ceiling rounding to whole recipients, applied per block before any cross-block summation, and a final ceiling when converting recipients to printed flyers. No metric may be computed by summing raw values first and rounding afterward where a per-term or per-block rounding order is specified; the rounding order is observable in the result.

### 2.10. Materials Stewardship and Inventory Conservation

The program distributes physical materials — watch signs and printed items such as decals and flyers — and tracks them as ledger fields on the watch group. `sign_inventory_count` records signs currently issued to the group and not yet recalled; `materials_inventory_count` records printed materials currently issued and not yet recalled. Both start at zero and may never go negative. Issuing materials adds the requested `signs` and `materials` quantities to the respective counts; recalling subtracts them. Two conservation rules guard the ledgers: a recall that would drive either count below zero is rejected with `ERR_INVENTORY_LIMIT` (HTTP 422), and sign distribution is capped by a precinct depot budget of 50 signs per group — an issue that would push a group's issued sign count past that budget is likewise rejected with `ERR_INVENTORY_LIMIT`. Every issue or recall increments the group's `version`. Separately, sending an alert consumes printed flyers computed from the alert's fan-out (see §3.4), and recalling a sent alert credits exactly the same flyer quantity back, so the materials ledger is conserved across the alert lifecycle.

### 2.11. Quiet Hours and Distribution Windows

Out of consideration for residents, alert distribution respects a daily quiet-hours window from 22:00 to 07:00 local time. An alert whose `scheduled_send_at` falls inside quiet hours is rejected with `ERR_QUIET_HOURS` (HTTP 422) at the time the schedule is set, and an immediate send attempted during quiet hours is rejected the same way. The single exemption is an alert whose `alert_kind` is `INCIDENT_BULLETIN`: incident bulletins may be scheduled into, and sent during, quiet hours, because timely notice of a corroborated incident outweighs the disturbance. All other kinds — `MEETING_NOTICE`, `EVENT_NOTICE`, and `SAFETY_TIP` — are bound by the window at both scheduling and sending time.

### 2.12. Segregation of Duties and Information Visibility

Two segregation-of-duties rules are enforced throughout. First, no one may review their own incident report: the coordinator who begins review of, or dismisses, a report must not be the member who filed it. Second, certification authority is separated from training delivery: the officer recorded as `reviewing_officer_id` on a certification review must differ from the officer who delivered the group's most recent completed `BIAS_AVOIDANCE` training session. A violation of either rule is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

Visibility of personal data is deliberately scoped. Each member's `roster_visibility` declares who may see their contact record: `GROUP_ONLY` (the default), `LIAISON_VISIBLE`, or `PROGRAM_WIDE`. A `LiaisonOfficer` listing members sees only those marked `LIAISON_VISIBLE` or `PROGRAM_WIDE`, unless the group holds an `ACTIVE` data-sharing agreement whose `scope` is `ROSTER_CONTACTS` or `FULL`, in which case the roster opens to the officer. Incident reports are similarly gated: an officer may read an individual report only when the report's `shared_with_liaison` flag is true or an `ACTIVE` agreement of scope `INCIDENT_SUMMARIES` or `FULL` covers the group; otherwise the read is rejected with `ERR_DATA_SHARE_REQUIRED`. When an agreement is revoked or expires, every report shared under it is re-scoped — the reports remain in their review states, but new liaison reads are denied — and the roster enforcement tightens back to the members' declared `roster_visibility`.

## 3. Business Logic & Workflows

### 3.1. Founding a Group and Registering Its Blocks

A `ProgramCoordinator` founds a watch group by supplying its official program `name` and the `precinct_code` of the sponsoring police precinct. The name must be between 1 and 120 characters and must be unique among the groups sponsored by the same precinct; the precinct code is an uppercase alphanumeric code of 2 to 12 characters. A new group begins with `certification_status` of `UNCERTIFIED` and `posture` of `DORMANT`, with `certification_valid_until` null — it remains null while the group is `UNCERTIFIED` or `REVOKED` — and both inventory ledgers and the `participation_score` at zero. The `training_cooldown_until` field is likewise null until a cooldown is armed.

Blocks are added to the group with a human-readable `street_segment` (for example, "100-199 Maple St") and a `household_count` of at least one; a `household_count` below 1 fails field-level validation with `ERR_INVALID_REQUEST`. The `street_segment` must be unique within the group among blocks that have not been deregistered; a duplicate is rejected with `ERR_CONSTRAINT_VIOLATION`. Each new block starts in `registration_status` `PENDING`, with `risk_heat_score` at zero and `last_incident_at` null until a corroborated or cleared incident exists.

Registration promotes a block from `PENDING` to `REGISTERED`. It is permitted only while the group's `certification_status` is anything other than `REVOKED`, and only while no other `REGISTERED` block of the same group already claims the same `street_segment` under a case-insensitive comparison — a case-variant duplicate is rejected with `ERR_CONSTRAINT_VIOLATION`. Registration is the event that wakes a group: when a group's first block reaches `REGISTERED` — provided the group's certification is `UNCERTIFIED` or `PROVISIONAL` — the group's `posture` recomputes from `DORMANT` to `FORMATION`, the participation score is recomputed under its census variant, and the group's `version` increments.

Deregistration moves a block from `REGISTERED` to `DEREGISTERED`, its terminal state. The path is guarded twice: no incident report filed against the block may be in `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_INFO` — open reports must be resolved first — and no `ACTIVE` captain assignment may exist for the block, so the captain must be relieved or revoked beforehand. Deregistering cascades: every `ACTIVE` member whose `block_id` names this block is withdrawn to `WITHDRAWN`, the group's participation score is recomputed, and the group's `version` increments. A transition attempted from the wrong state — registering a block that is not `PENDING`, or deregistering one that is not `REGISTERED` — is rejected with `ERR_INVALID_STATE` (HTTP 409), as is any action attempted against a terminal state or fired twice.

### 3.2. Membership and Block Captaincy

Members are the volunteer backbone of a group. Enrollment — open to a `ProgramCoordinator` or a `BlockCaptain` — records the member's `full_name`, the `watch_group_id` and `block_id` placing them in the program, their primary alert `contact_channel` of `SMS`, `EMAIL`, or `PHONE_TREE`, and optionally a `roster_visibility` that defaults to `GROUP_ONLY` when omitted. The block named by `block_id` must belong to the group named by `watch_group_id`; a cross-group pairing is rejected with `ERR_REFERENTIAL_INTEGRITY` (HTTP 422). A new member starts `ACTIVE` with `strike_count` zero and `bias_training_completed_at` null until they complete bias-avoidance training. Enrollment, like every member write, is gated by posture: while the group's posture is `FROZEN`, member creation is rejected with `ERR_POSTURE_GATED`. Each join recomputes the group's participation score.

A member's lifecycle runs from `ACTIVE` to `SUSPENDED` or `WITHDRAWN` (terminal). Suspension is a `ProgramCoordinator` action, and the system also suspends on its own authority when a member's `strike_count` reaches the strike limit of 3; both paths carry the same cascade. Suspending a member revokes any `ACTIVE` captain assignment they hold — the assignment's `assignment_status` becomes `REVOKED` and its `relieved_at` is stamped — and that vacancy recomputes the group's posture, which can force a group from `OPERATIONAL` down to `DEGRADED`. Reinstatement returns a `SUSPENDED` member to `ACTIVE`, resets `strike_count` to zero, and recomputes participation; it is refused with `ERR_POSTURE_GATED` while the group is `FROZEN`. Withdrawal from `ACTIVE` may be initiated by the member themselves or by a coordinator, and relieves any active captaincy — the assignment becomes `RELIEVED` rather than `REVOKED` — before recomputing posture and participation. A `SUSPENDED` member may be withdrawn only by a coordinator.

Each registered block is led by exactly one captain. Appointment is a coordinator action naming a `member_id`, guarded by optimistic concurrency on the block per §2.7. The appointee must be an `ACTIVE` member of a block belonging to the same watch group as the block being captained — anything else is `ERR_REFERENTIAL_INTEGRITY` — and a member may hold at most one `ACTIVE` captain assignment across the program, enforced as `ERR_CONSTRAINT_VIOLATION`. Appointment carries supersede semantics: if the block already has an `ACTIVE` assignment, the new assignment becomes active and the prior one is relieved to `RELIEVED` with `relieved_at` stamped. The assignment records `assigned_at` when it becomes active; `relieved_at` stays null while the assignment is `ACTIVE`. A coordinator may also relieve an active assignment directly, moving it to `RELIEVED`; either path recomputes posture, and a vacated registered block takes the group from `OPERATIONAL` to `DEGRADED`, which holds the group's queued alerts until coverage returns. When the vacancy is filled and every `REGISTERED` block again holds exactly one `ACTIVE` assignment, posture recomputes from `DEGRADED` back to `OPERATIONAL` and the held queued alerts become sendable again.

### 3.3. Incident Intake, Review, and Pattern Mapping

Members and captains file incident reports against a block, supplying the `block_id`, the filing member's `reporter_member_id`, a `category` of `SUSPICIOUS_ACTIVITY`, `PROPERTY_CRIME`, `VANDALISM`, `NOISE`, `TRAFFIC`, or `OTHER`, the `occurred_at` timestamp of the incident, and a reporter-assessed `severity` from 1 to 5. The reporter must be an `ACTIVE` member of the group that owns the block, on pain of `ERR_REFERENTIAL_INTEGRITY`. An `occurred_at` in the future relative to the logical clock, or a `severity` outside the 1-to-5 band, fails with `ERR_INVALID_REQUEST`. Reports are born in `review_status` `SUBMITTED` with `corroboration_weight` zero and `shared_with_liaison` false.

Review is a cyclic pipeline. A coordinator moves a `SUBMITTED` report to `UNDER_REVIEW`, and — per the segregation rule of §2.12 — may do so only if their user id differs from the `reporter_member_id`; self-review is rejected with `ERR_SEGREGATION_OF_DUTIES`. While `UNDER_REVIEW`, the coordinator may bounce the report to `NEEDS_INFO`, which returns it to the reporter for clarification. Resubmission from `NEEDS_INFO` back to `UNDER_REVIEW` is restricted to the original reporter — the acting member's id must equal `reporter_member_id`, and anyone else is refused with `ERR_REPORTER_ONLY` (HTTP 403). From `UNDER_REVIEW` the report can end three ways. Dismissal by a coordinator — again not the reporter, else `ERR_SEGREGATION_OF_DUTIES` — moves it to `DISMISSED`, terminal, with `corroboration_weight` staying zero. Corroboration by a `LiaisonOfficer` moves it to `CORROBORATED`, but only when an `ACTIVE` data-sharing agreement of scope `INCIDENT_SUMMARIES` or `FULL` covers the report's group; without one the transition is rejected with `ERR_DATA_SHARE_REQUIRED`. Clearing, also an officer action, moves a `CORROBORATED` report to `CLEARED`, terminal. Every one of these transitions increments the report's `version`.

Corroboration is where pattern mapping begins. When a report reaches `CORROBORATED`, its `corroboration_weight` is set per the heat calculation below, `shared_with_liaison` flips to true, the block's `risk_heat_score` is recomputed, `last_incident_at` is updated to reflect the most recent corroborated or cleared report on the block, and the group's participation score is recomputed under its activity variant. Clearing recomputes the report's weight under the cleared weighting and recomputes the block's heat again.

The heat calculation is a step-decay over 30-day buckets, measured in whole days from the report's `occurred_at` to the current logical clock. A report aged no more than 30 days contributes at full weight; more than 30 and no more than 60 days contributes at half weight; more than 60 and no more than 90 days contributes at one-quarter weight; anything older contributes nothing. Each report's contribution is its `severity` multiplied by its bucket weight, rounded half-up to two decimal places per report, and the block's `risk_heat_score` is the sum of those rounded contributions over the block's reports in `CORROBORATED` or `CLEARED`. The calculation runs in one of two variants. While an `ACTIVE` data-sharing agreement covers the group, both corroborated and cleared reports contribute. Once no active agreement covers the group — because it was revoked or expired — the corroborated-only variant applies: cleared reports whose disclosure was revoked contribute zero, while corroborated reports continue to contribute. This is why revoking or expiring an agreement recomputes every affected block's heat.

### 3.4. Alerts: Drafting, Fan-Out, and Acknowledgement

Alerts are the program's distribution channel, drafted by a coordinator or a captain. A draft carries the issuing `watch_group_id`, an `alert_kind` of `INCIDENT_BULLETIN`, `MEETING_NOTICE`, `EVENT_NOTICE`, or `SAFETY_TIP`, an `audience_scope` of `BLOCK` or `GROUP`, and a `scheduled_send_at` that must sit outside quiet hours unless the alert is an incident bulletin (§2.11). Drafting also carries the group's expected version per §2.7. When the scope is `BLOCK`, a `target_block_id` is required and must name a block of the same group — a foreign target is `ERR_REFERENTIAL_INTEGRITY` — and `target_block_id` is forbidden when the scope is `GROUP`. When the kind is `INCIDENT_BULLETIN`, an `origin_incident_id` is required; it is optional otherwise. Because a block that loses its captain drags its group toward `DEGRADED`, the active-captain requirement for block-scoped alerts is verified at creation time — the target block must hold exactly one `ACTIVE` captain assignment, else `ERR_NO_ACTIVE_CAPTAIN` (HTTP 409) — so the captainless-block case surfaces instead of being masked by the posture gate that guards queueing and sending. Drafting is accepted in any posture other than `FROZEN` — `DORMANT` and `FORMATION` groups may draft alerts just as `OPERATIONAL` and `DEGRADED` ones may; a `FROZEN` group alone rejects alert writes with `ERR_POSTURE_GATED`, the posture gate otherwise guarding queueing and sending rather than drafting. A new alert starts with `distribution_status` `DRAFT`, `ack_posture` `UNTRACKED`, and `recipient_count` and `ack_count` at zero.

Queueing — available to a coordinator or a captain — moves a draft from `DRAFT` to `QUEUED`. It requires the group's posture to be exactly `OPERATIONAL`, failing with `ERR_POSTURE_GATED` otherwise, and for an incident bulletin it additionally requires the origin incident to be in `CORROBORATED` or `CLEARED`; queueing anything else is `ERR_INVALID_STATE`. A queued alert may be pulled back to `DRAFT` by a coordinator. Sending moves `QUEUED` to `SENT`; only a coordinator may send explicitly, and the system itself sends when the logical clock reaches `scheduled_send_at`. Sending before the scheduled instant is rejected with `ERR_INVALID_STATE` — the scheduled instant itself is fireable — and sending still requires posture `OPERATIONAL` and the quiet-hours rule of §2.11. Should the group slip from `OPERATIONAL` to `DEGRADED` while alerts sit queued, those alerts are held in place: their `distribution_status` stays `QUEUED`, sends are rejected with `ERR_POSTURE_GATED`, and they become sendable again only when coverage is restored and posture returns to `OPERATIONAL`.

Sending is where the fan-out is computed. The in-scope blocks are the single target block for a `BLOCK` alert, or every `REGISTERED` block of the group for a `GROUP` alert. For each in-scope block, the raw reach is the count of the block's `ACTIVE` members on `SMS`, plus the count on `EMAIL`, plus the count on `PHONE_TREE` multiplied by 2.5 — each phone-tree member relays to two and a half households on average — and that raw figure is rounded up to a whole number of recipients for that block before anything is summed. The alert's `recipient_count` is the sum of those per-block ceilings. The rounding order is pinned and observable: two blocks each holding a single `PHONE_TREE` member yield 3 plus 3, that is 6 recipients, because each block's raw 2.5 is rounded up individually; collapsing the sum first would wrongly produce 5. Only `ACTIVE` members count; `SUSPENDED` and `WITHDRAWN` members are excluded. The same transition charges the materials ledger: the group is deemed to print one flyer per 10 recipients, rounded up, and `materials_inventory_count` increases by that flyer quantity. Recalling a `SENT` alert — a coordinator action — moves it to `RECALLED`, terminal, and credits back exactly the flyer quantity that was added at send, conserving the ledger; the alert's `ack_posture` is frozen at whatever value it held at recall.

Acknowledgement runs on a parallel dimension. A member or captain records an acknowledgement by supplying their `member_id`; each acknowledgement increments `ack_count`, and a second acknowledgement from the same member is rejected with `ERR_CONSTRAINT_VIOLATION`. The `ack_posture` derives from the counts: it leaves `UNTRACKED` for `PARTIAL` once at least one member has acknowledged, advances to `MAJORITY` once `ack_count` reaches at least half of `recipient_count` rounded down plus one, and reaches `FULL` when `ack_count` equals `recipient_count` with a nonzero recipient count.

### 3.5. Liaison Meetings and Data-Sharing Agreements

The department's side of the program starts with its officers. A coordinator registers each officer with a unique `badge_number` — duplicates are rejected with `ERR_CONSTRAINT_VIOLATION` — a `full_name`, and the `precinct_code` the officer is assigned to.

A `LiaisonOfficer` chairs liaison meetings with a group, scheduling one by naming the `watch_group_id`, the chairing `liaison_officer_id`, and a room reservation from `room_slot_start` to `room_slot_end`. The end must come after the start, failing `ERR_INVALID_REQUEST` otherwise. The reservation is a half-open interval — it occupies from the start up to but not including the end — and it must not overlap any other `SCHEDULED` or `HELD` meeting's slot in the same precinct; overlap is rejected with `ERR_ROOM_SLOT_CONFLICT`, while adjacency, where one meeting's end equals the other's start, is allowed. A meeting begins in `meeting_status` `SCHEDULED`.

Marking a meeting held is the chairing officer's act: the acting officer's id must equal the meeting's `liaison_officer_id`, the logical clock must have reached `room_slot_start`, and the request carries the `attendee_count` of members present — zero or more, and settable only at this transition. Quorum is judged in a pinned order: first the system snapshots the count of the group's `ACTIVE` members at the instant of the mark-held call, before any side effect of the transition runs; then it computes the threshold as the larger of 2 and one quarter of that active count rounded up to a whole number; finally `quorum_met` is set to whether `attendee_count` is at least the threshold, with equality counting. When quorum is met, the group's participation score picks up the meeting input and is recomputed. Either the chairing officer or a coordinator may cancel a `SCHEDULED` meeting, moving it to `CANCELLED` and releasing the room slot for others.

Data sharing is formalized per group. A coordinator drafts an agreement naming the `watch_group_id`, the receiving `liaison_officer_id`, a `scope` of `INCIDENT_SUMMARIES`, `ROSTER_CONTACTS`, or `FULL`, and an `expires_at`; the officer's precinct must match the group's `precinct_code`, else `ERR_REFERENTIAL_INTEGRITY`. The agreement begins in `agreement_status` `PENDING`. Activation is the receiving officer's act — the acting officer must be the agreement's `liaison_officer_id`, the precinct match is checked again, and the logical clock must not yet have reached `expires_at` — moving the agreement to `ACTIVE`. From `ACTIVE` there are two exits, both terminal. Revocation, available to either a coordinator or the officer, moves it to `REVOKED`; and the lazy expiry of §2.5 moves it to `EXPIRED` when the clock reaches `expires_at`. Both exits run the same cascade: every incident report of the group with `shared_with_liaison` true is re-scoped — the reports remain `CORROBORATED` or `CLEARED`, but new liaison reads are denied — roster enforcement tightens to the declared `roster_visibility`, and each affected block's heat is recomputed under the corroborated-only variant, excluding cleared reports whose disclosure has lapsed.

### 3.6. Training and the Cooling-Off Rule

Officers deliver training to a group by scheduling a session with the `watch_group_id`, the delivering `trainer_officer_id`, a `curriculum` of `BIAS_AVOIDANCE`, `OBSERVATION_SKILLS`, or `REPORT_WRITING`, and a `scheduled_at` start time. To keep sessions from bunching, a group that has completed a session enters a 24-hour cooling-off period: the group's `training_cooldown_until` is set to the completed session's `scheduled_at` plus 24 hours, and any new session whose `scheduled_at` precedes `training_cooldown_until` is rejected with `ERR_TRAINING_COOLDOWN`. Sessions are born in `session_status` `SCHEDULED`.

Completion is the delivering officer's act — the acting officer must equal `trainer_officer_id` — and requires a non-empty `attending_member_ids` list in which every id names an `ACTIVE` member of the same group. Completing a session stamps each attending member's training: for a `BIAS_AVOIDANCE` curriculum, each attendee's `bias_training_completed_at` is set to the session's `scheduled_at`. Completion also arms the group's cooldown as above and recomputes posture — completion of the group's first bias-avoidance session is one of the two gates on the path from `FORMATION` to `OPERATIONAL`. Either the officer or a coordinator may cancel a `SCHEDULED` session, moving it to `CANCELLED` with no further effect.

### 3.7. Community Events and Street Closures

Groups host community events — `NATIONAL_NIGHT_OUT`, `BLOCK_PARTY`, or `SAFETY_FAIR` — proposed by a coordinator or a captain with the `watch_group_id`, the `event_kind`, a street-closure window from `street_closure_start` to `street_closure_end`, and an `estimated_attendance` of zero or more. The closure end must be at or after its start, failing `ERR_INVALID_REQUEST` otherwise, and proposing while the group is `FROZEN` is refused with `ERR_POSTURE_GATED`. Events are born in `event_status` `PROPOSED`.

Street closures are checked with buffer-inclusive semantics, because setup and teardown bleed past the advertised window. A two-hour buffer is prepended to `street_closure_start` and appended to `street_closure_end`, and the resulting buffered closed interval must not touch the buffered window of any other `APPROVED` event of the same group — zero-gap adjacency is forbidden, so the gap between two buffered windows must be greater than zero. A collision is rejected with `ERR_CLOSURE_CONFLICT`, and the check runs both at proposal and again at approval.

Approval is a `LiaisonOfficer` action that moves the event from `PROPOSED` to `APPROVED`, and it carries two gates beyond the closure check. The checks are evaluated in the priority order of §2.6 — the closure-conflict re-check first, then the data-sharing gate, then the certification gate — so a closure conflict surfaces before either gate, and a data-share shortfall surfaces before any certification shortfall. The certification gate requires the group's `certification_status` to be `CERTIFIED` for a `NATIONAL_NIGHT_OUT`, and either `PROVISIONAL` or `CERTIFIED` for the other kinds; a shortfall is rejected with `ERR_CERTIFICATION_REQUIRED`. The large-gathering notification rule requires the group to hold an `ACTIVE` data-sharing agreement whenever `estimated_attendance` reaches the permit tier of 100 or more; without one, approval is rejected with `ERR_DATA_SHARE_REQUIRED`. After the closure window has fully passed — the logical clock is later than `street_closure_end` — a coordinator completes the event, moving it from `APPROVED` to `COMPLETED` and recomputing the group's participation score with the event input. Cancellation splits by state and role: a coordinator may cancel while the event is `PROPOSED`, and an officer may cancel an `APPROVED` event only while the logical clock is still earlier than `street_closure_start`, which releases the street-closure window; both paths end in `CANCELLED`, terminal.

### 3.8. Certification Reviews and the Participation Score

Certification is the program's quality gate, decided per group through a review. A coordinator opens a review by naming the `watch_group_id` and the `reviewing_officer_id`; per §2.12 the reviewing officer must not be the officer who delivered the group's most recent completed `BIAS_AVOIDANCE` session, enforced at both opening and decision time with `ERR_SEGREGATION_OF_DUTIES`. Only one open review per group is allowed: opening a second while a `PENDING` or `CONDITIONAL` review exists is rejected with `ERR_DUPLICATE`. A review opens in `review_status` `PENDING`, and its `certification_points` composite is computed at creation and recomputed fresh on every decision call.

The composite scores five terms over the group's children. The membership term is one point per `ACTIVE` member whose `bias_training_completed_at` is set, capped at 25. The meetings term is five points per `HELD` liaison meeting with `quorum_met` true, capped at 25. The events term is 20 points when a `COMPLETED` `NATIONAL_NIGHT_OUT` exists for the group, otherwise 10 points when any `COMPLETED` event exists, otherwise zero. The captaincy term is 15 points when every `REGISTERED` block holds exactly one `ACTIVE` captain assignment, otherwise zero. The alerts term is 15 points when the group has at least three alerts in `SENT`, otherwise 5 points when it has at least one, otherwise zero. All arithmetic is integer; the review's `certification_points` is the sum of the five terms.

Decision is the reviewing officer's act — the acting officer must equal `reviewing_officer_id` — expressed through a `decision` of `APPROVED`, `REJECTED`, or `CONDITIONAL`, and the thresholds shape each branch. From `PENDING`, an `APPROVED` decision requires the recomputed points to be at least 60; it sets the group's `certification_status` to `CERTIFIED` when the points reach 80 or more and to `PROVISIONAL` below that, grants 24 months of validity at the full threshold or 12 months below it in `certification_grant_months`, sets `certification_valid_until` to the current moment plus the granted months, and recomputes posture. A `REJECTED` decision from `PENDING` sets the group's certification to `UNCERTIFIED` — with one sharpening: when the group was previously `CERTIFIED` and the rejected review was a renewal, the standing falls to `REVOKED` instead. A `CONDITIONAL` decision from `PENDING` requires the points to be at least 40 and below 60 and sets certification to `PROVISIONAL`; `certification_grant_months` is zero whenever the review is not approved. A `CONDITIONAL` review can later be decided again: approval after remediation requires the recomputed points to be at least 60 and carries the same effects as an approval from `PENDING`, and rejection carries the same effects as a rejection from `PENDING`. Both `APPROVED` and `REJECTED` are terminal for the review.

Two administrative levers sit beside the review pipeline. A coordinator may suspend a group's program standing, moving `certification_status` from `UNCERTIFIED`, `PROVISIONAL`, or `CERTIFIED` to `SUSPENDED`; calling it on a group already `SUSPENDED` or `REVOKED` is not a no-op — it fails with `ERR_INVALID_STATE`. The remediation path reinstates a `SUSPENDED` standing to `PROVISIONAL` and recomputes posture. A suspended standing is what unlocks the freeze: a coordinator may freeze a group whose `certification_status` is `SUSPENDED`, moving posture from `OPERATIONAL`, `DEGRADED`, or `FORMATION` to `FROZEN`. A frozen group's roster is read-only — member writes are rejected with `ERR_POSTURE_GATED` — and once certification returns to `PROVISIONAL` or `CERTIFIED`, unfreezing moves the group from `FROZEN` back to `OPERATIONAL` with posture recomputed from scratch. Each of these administrative moves increments the group's `version`.

Underneath posture sits the participation score, the program's public metric of vitality, recomputed whenever the facts change: posture recomputes, members joining, withdrawing, being suspended, or reinstated, a meeting held with quorum, an event completed, an incident corroborated. The score runs in two variants selected by posture. While the group is `DORMANT` or `FORMATION`, the census variant counts only the forward-looking base: 10 points per `REGISTERED` block plus 2 points per `ACTIVE` member. Once the group is `OPERATIONAL`, `DEGRADED`, or `FROZEN`, the activity variant adds the trailing record on top of the same base: 5 points per `HELD` meeting with quorum, 8 points per `COMPLETED` event, and 3 points per incident report in `CORROBORATED` or `CLEARED`. All of it is integer arithmetic with no fractional rounding, and the two variants deliberately produce different values for identical raw data — a group's score steps the moment its posture crosses the boundary, because different terms enter the sum.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; operations that modify, transition, or act on an existing resource return `200 OK`. List endpoints accept the pagination parameters of §2.3 plus the filter parameters noted in their descriptions; readers should reconstruct full request payloads from the narratives of §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/watch/_clock/set_current_utc` | Set the server's logical clock to a supplied instant | ProgramCoordinator |
| POST | `/watch/watch-groups` | Create a neighborhood watch group | ProgramCoordinator |
| GET | `/watch/watch-groups` | List watch groups; filterable by `precinct_code`, `certification_status`, `posture` | ProgramCoordinator, LiaisonOfficer, BlockCaptain, Member |
| GET | `/watch/watch-groups/{id}` | Fetch one watch group, including derived posture, participation score, and inventories | ProgramCoordinator, LiaisonOfficer, BlockCaptain, Member |
| POST | `/watch/watch-groups/{id}/certification-suspend` | Suspend a group's program standing | ProgramCoordinator |
| POST | `/watch/watch-groups/{id}/certification-reinstate` | Reinstate a suspended standing to `PROVISIONAL` | ProgramCoordinator |
| POST | `/watch/watch-groups/{id}/freeze` | Freeze a certification-suspended group | ProgramCoordinator |
| POST | `/watch/watch-groups/{id}/unfreeze` | Unfreeze a group whose standing has been remediated | ProgramCoordinator |
| POST | `/watch/watch-groups/{id}/materials/issue` | Issue signs and printed materials to a group | ProgramCoordinator |
| POST | `/watch/watch-groups/{id}/materials/recall` | Recall signs and materials from a group | ProgramCoordinator |
| POST | `/watch/watch-groups/{id}/blocks` | Add a block to a watch group | ProgramCoordinator |
| GET | `/watch/watch-groups/{id}/blocks` | List a group's blocks; filterable by `registration_status` | ProgramCoordinator, LiaisonOfficer, BlockCaptain, Member |
| GET | `/watch/blocks/{id}` | Fetch one block, including its heat score | ProgramCoordinator, LiaisonOfficer, BlockCaptain, Member |
| POST | `/watch/blocks/{id}/register` | Register a `PENDING` block | ProgramCoordinator |
| POST | `/watch/blocks/{id}/deregister` | Deregister a `REGISTERED` block, cascading member withdrawal | ProgramCoordinator |
| POST | `/watch/members` | Enroll a member in a group on a block | ProgramCoordinator, BlockCaptain |
| GET | `/watch/members` | List members, scoped by roster visibility; filterable by `watch_group_id`, `block_id`, `membership_status` | ProgramCoordinator, LiaisonOfficer, BlockCaptain, Member |
| GET | `/watch/members/{id}` | Fetch one member | ProgramCoordinator, LiaisonOfficer, BlockCaptain, Member |
| POST | `/watch/members/{id}/suspend` | Suspend an `ACTIVE` member, cascading captain revocation | ProgramCoordinator |
| POST | `/watch/members/{id}/reinstate` | Reinstate a `SUSPENDED` member and reset strikes | ProgramCoordinator |
| POST | `/watch/members/{id}/withdraw` | Withdraw a member (self-service or coordinator) | ProgramCoordinator, Member |
| POST | `/watch/blocks/{id}/captain-assignments` | Appoint a block captain with supersede semantics; OCC-guarded on the block | ProgramCoordinator |
| GET | `/watch/blocks/{id}/captain-assignments` | List a block's captain assignments, history included; filterable by `assignment_status` | ProgramCoordinator, LiaisonOfficer, BlockCaptain, Member |
| GET | `/watch/captain-assignments` | List captain assignments across blocks; filterable by `member_id`, `block_id`, `assignment_status` | ProgramCoordinator, LiaisonOfficer, BlockCaptain, Member |
| GET | `/watch/captain-assignments/{id}` | Fetch one captain assignment | ProgramCoordinator, LiaisonOfficer, BlockCaptain, Member |
| POST | `/watch/captain-assignments/{id}/relieve` | Relieve an `ACTIVE` captain assignment | ProgramCoordinator |
| POST | `/watch/incident-reports` | File an incident report | Member, BlockCaptain |
| GET | `/watch/incident-reports` | List incident reports; filterable by `block_id`, `reporter_member_id`, `review_status`, `category` | ProgramCoordinator, LiaisonOfficer, BlockCaptain, Member |
| GET | `/watch/incident-reports/{id}` | Fetch one incident report; liaison reads are data-share gated | ProgramCoordinator, LiaisonOfficer, BlockCaptain, Member |
| POST | `/watch/incident-reports/{id}/begin-review` | Move a report from `SUBMITTED` to `UNDER_REVIEW` | ProgramCoordinator |
| POST | `/watch/incident-reports/{id}/request-info` | Bounce a report from `UNDER_REVIEW` to `NEEDS_INFO` | ProgramCoordinator |
| POST | `/watch/incident-reports/{id}/resubmit` | Resubmit a `NEEDS_INFO` report to `UNDER_REVIEW`; reporter only | Member, BlockCaptain |
| POST | `/watch/incident-reports/{id}/corroborate` | Corroborate an `UNDER_REVIEW` report | LiaisonOfficer |
| POST | `/watch/incident-reports/{id}/dismiss` | Dismiss an `UNDER_REVIEW` report | ProgramCoordinator |
| POST | `/watch/incident-reports/{id}/clear` | Clear a `CORROBORATED` report | LiaisonOfficer |
| POST | `/watch/alerts` | Create an alert in `DRAFT`; OCC-guarded on the watch group | ProgramCoordinator, BlockCaptain |
| GET | `/watch/alerts` | List alerts; filterable by `watch_group_id`, `origin_incident_id`, `target_block_id`, `distribution_status`, `alert_kind` | ProgramCoordinator, LiaisonOfficer, BlockCaptain, Member |
| GET | `/watch/alerts/{id}` | Fetch one alert, including its acknowledgement posture | ProgramCoordinator, LiaisonOfficer, BlockCaptain, Member |
| POST | `/watch/alerts/{id}/queue` | Move an alert from `DRAFT` to `QUEUED` | ProgramCoordinator, BlockCaptain |
| POST | `/watch/alerts/{id}/send` | Send a `QUEUED` alert, computing its fan-out | ProgramCoordinator |
| POST | `/watch/alerts/{id}/unqueue` | Pull a `QUEUED` alert back to `DRAFT` | ProgramCoordinator |
| POST | `/watch/alerts/{id}/recall` | Recall a `SENT` alert, compensating the materials ledger | ProgramCoordinator |
| POST | `/watch/alerts/{id}/ack` | Record a member acknowledgement of an alert | Member, BlockCaptain |
| POST | `/watch/liaison-officers` | Register a liaison officer | ProgramCoordinator |
| GET | `/watch/liaison-officers` | List liaison officers; filterable by `precinct_code` | ProgramCoordinator, LiaisonOfficer |
| GET | `/watch/liaison-officers/{id}` | Fetch one liaison officer | ProgramCoordinator, LiaisonOfficer |
| POST | `/watch/liaison-meetings` | Schedule a liaison meeting with a room-slot conflict check | LiaisonOfficer |
| GET | `/watch/liaison-meetings` | List liaison meetings; filterable by `watch_group_id`, `liaison_officer_id`, `meeting_status` | ProgramCoordinator, LiaisonOfficer, BlockCaptain, Member |
| GET | `/watch/liaison-meetings/{id}` | Fetch one liaison meeting | ProgramCoordinator, LiaisonOfficer, BlockCaptain, Member |
| POST | `/watch/liaison-meetings/{id}/mark-held` | Mark a meeting `HELD`, computing quorum | LiaisonOfficer |
| POST | `/watch/liaison-meetings/{id}/cancel` | Cancel a `SCHEDULED` meeting | LiaisonOfficer, ProgramCoordinator |
| POST | `/watch/data-share-agreements` | Draft a data-sharing agreement in `PENDING` | ProgramCoordinator |
| GET | `/watch/data-share-agreements` | List agreements; filterable by `watch_group_id`, `liaison_officer_id`, `agreement_status` | ProgramCoordinator, LiaisonOfficer |
| GET | `/watch/data-share-agreements/{id}` | Fetch one agreement | ProgramCoordinator, LiaisonOfficer |
| POST | `/watch/data-share-agreements/{id}/activate` | Activate a `PENDING` agreement | LiaisonOfficer |
| POST | `/watch/data-share-agreements/{id}/revoke` | Revoke an `ACTIVE` agreement, cascading re-scoping | ProgramCoordinator, LiaisonOfficer |
| POST | `/watch/training-sessions` | Schedule a training session, honoring the group cooldown | LiaisonOfficer |
| GET | `/watch/training-sessions` | List training sessions; filterable by `watch_group_id`, `trainer_officer_id`, `session_status`, `curriculum` | ProgramCoordinator, LiaisonOfficer, BlockCaptain, Member |
| GET | `/watch/training-sessions/{id}` | Fetch one training session | ProgramCoordinator, LiaisonOfficer, BlockCaptain, Member |
| POST | `/watch/training-sessions/{id}/complete` | Complete a session, stamping attendees and arming the cooldown | LiaisonOfficer |
| POST | `/watch/training-sessions/{id}/cancel` | Cancel a `SCHEDULED` session | LiaisonOfficer, ProgramCoordinator |
| POST | `/watch/community-events` | Propose a community event with a buffer-inclusive closure check | ProgramCoordinator, BlockCaptain |
| GET | `/watch/community-events` | List community events; filterable by `watch_group_id`, `event_status`, `event_kind` | ProgramCoordinator, LiaisonOfficer, BlockCaptain, Member |
| GET | `/watch/community-events/{id}` | Fetch one community event | ProgramCoordinator, LiaisonOfficer, BlockCaptain, Member |
| POST | `/watch/community-events/{id}/approve` | Approve a `PROPOSED` event under closure, attendance, and certification gates | LiaisonOfficer |
| POST | `/watch/community-events/{id}/complete` | Complete an `APPROVED` event after its closure ends | ProgramCoordinator |
| POST | `/watch/community-events/{id}/cancel` | Cancel a proposed event (coordinator) or an approved one before closure start (officer) | ProgramCoordinator, LiaisonOfficer |
| POST | `/watch/certification-reviews` | Open a certification review for a group | ProgramCoordinator |
| GET | `/watch/certification-reviews` | List certification reviews; filterable by `watch_group_id`, `reviewing_officer_id`, `review_status` | ProgramCoordinator, LiaisonOfficer |
| GET | `/watch/certification-reviews/{id}` | Fetch one certification review | ProgramCoordinator, LiaisonOfficer |
| POST | `/watch/certification-reviews/{id}/decide` | Decide a review as `APPROVED`, `REJECTED`, or `CONDITIONAL` | LiaisonOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_POSTURE_GATED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_QUIET_HOURS` | 422 Unprocessable Entity |
| `ERR_ROOM_SLOT_CONFLICT` | 409 Conflict |
| `ERR_CLOSURE_CONFLICT` | 409 Conflict |
| `ERR_TRAINING_COOLDOWN` | 422 Unprocessable Entity |
| `ERR_REFERENTIAL_INTEGRITY` | 422 Unprocessable Entity |
| `ERR_CONSTRAINT_VIOLATION` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVENTORY_LIMIT` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DATA_SHARE_REQUIRED` | 409 Conflict |
| `ERR_CERTIFICATION_REQUIRED` | 409 Conflict |
| `ERR_NO_ACTIVE_CAPTAIN` | 409 Conflict |
| `ERR_REPORTER_ONLY` | 403 Forbidden |
| `ERR_DUPLICATE` | 409 Conflict |
