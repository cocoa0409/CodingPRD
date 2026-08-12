# Amateur Radio Club & Emergency Communications API — Product Requirements Document

## 1. Introduction

An ARRL-affiliated amateur radio club runs far more than a membership roster. Its officers coordinate repeater infrastructure through a regional frequency council, negotiate antenna site leases with landowners, staff weekly nets, maintain emergency-communications readiness under formal served-agency agreements, administer FCC license exam sessions, run the annual Field Day operating event, and lend club-owned equipment to members in good standing. Each of these functions carries its own compliance surface — license classes are ordinal credentials, frequency authorizations come from an outside body, emergency activations demand segregation of duties, and equipment losses feed back into a member's standing. This document specifies the REST API that becomes the club's system of record for all of it.

The design is deliberately event-driven and time-aware. Membership standing lapses when dues run out, site leases expire, loans become overdue, and served-agency agreements lapse — all evaluated against a controllable logical clock rather than wall-clock time. A member's emergency readiness is a scored, tiered quantity computed from trailing-twelve-month participation, and that score gates who may be confirmed onto an activation roster. Because a single administrative action (a site lease expiring, a repeater going offline, an equipment return marked damaged) can ripple through repeaters, nets, readiness scores, and rosters, the cascades are specified as precisely as the primary operations themselves.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` identifying the acting user and `X-User-Role` declaring the operational capacity. The system recognizes exactly five roles, spelled as follows: `ClubAdmin`, `Member`, `NetControl`, `EmergencyCoordinator`, and `ExamLiaison`. A request missing either header, presenting a role outside this set, or — for the entity-backed roles below — presenting an `X-User-ID` that does not reference an existing club member is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not listed for the target endpoint, or that fails a declared ownership sub-check (a net control acting on another operator's net, a member touching another member's roster entry, loan, contact, or message), is rejected with `ERR_FORBIDDEN`.

The five roles resolve their identity differently:

- When `X-User-Role` is `ClubAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`.
- When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's member foreign-key field to `X-User-ID`.
- When `X-User-Role` is `NetControl`, `X-User-ID` is likewise the `id` of the acting `Member`, and the operator owns exactly those nets whose `net_control_member_id` equals it.
- When `X-User-Role` is `EmergencyCoordinator`, `X-User-ID` is the `id` of the acting `Member`; activation and roster custody is tracked through that member identity (for example, the member recorded as `activated_by_member_id` on an activation).
- When `X-User-Role` is `ExamLiaison`, `X-User-ID` is the `id` of the acting `Member`; exam custody is tracked through that member identity (for example, the member recorded as `checked_in_by_member_id` on a candidate).

The role model follows segregation of duties: emergency demobilization must be performed by a different member than the one who activated, and exam result recording must be performed by a different member than the one who checked the candidate in. Those two rules carry dedicated error codes and are detailed in §3.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the club logical clock of §2.5 (not wall-clock time).
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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Values outside those ranges are clamped to the nearest bound, and a non-numeric `limit` or `offset` falls back to its default. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by insertion order. A filter value that matches no resources yields an empty page (`data` is an empty array, `total_count` zero) rather than an error. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

All primary resources in the system share a standard set of system-managed fields:

- `id` (string): a unique, server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set once at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments by one on every mutation of the resource, including mutations caused by cascades originating on other entities.

The one exception is the check-in record. A `CheckIn` carries only `id` and `created_at`; both `updated_at` and `version` are absent, because a check-in is immutable once written. Every mutation described in §3 — status transitions, renewals, recorded decisions, computed-field recomputation, and cascade hops — counts as a mutation on the touched resource: it refreshes `updated_at` and increments `version`.

### 2.5. The Club Logical Clock and Scheduled State Evaluation

All time-sensitive rules in the system are evaluated against a **logical clock**, never against wall-clock time. At server startup the logical clock reads exactly `2026-05-01T00:00:00Z`; until an operator explicitly sets it, every rule that consults "now" uses that default. A `ClubAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant. The endpoint performs no monotonicity or direction check: the supplied instant is adopted as-is, even when it is earlier than the current reading, and the transition sequence below is evaluated against the new reading on every call. This endpoint is the single unauthenticated surface of the API: the header checks of §2.1 do not apply to it, though callers are still expected to identify as `ClubAdmin` in practice and the endpoint is documented as `ClubAdmin`-scoped in §4.

Setting the clock is not a passive read change — it fires a fixed sequence of system-evaluated transitions, in this order:

1. Every member whose dues window has been passed transitions from `ACTIVE` to `LAPSED`, and their readiness fields are recomputed.
2. Every antenna site agreement whose `lease_end` has been passed transitions from `ACTIVE` to `EXPIRED`, firing the full repeater/net/readiness cascade described in §2.6.
3. Every served-agency agreement whose `effective_end` has been passed transitions from `ACTIVE` to `EXPIRED`, cancelling any `STANDBY` activations under it with their roster cascade.
4. Every outstanding equipment loan whose `due_at` has been passed transitions from `ACTIVE` to `OVERDUE`.

Advancing the clock is the only way these time-triggered transitions occur; no background timer exists.

### 2.6. Cascading Consistency Across Sites, Repeaters, Nets, and Rosters

The club's infrastructure and emergency operations form a dependency graph, and the system maintains it aggressively. When a site agreement leaves `ACTIVE` — whether by clock expiry or by administrative termination — every repeater homed at that site is forced `OFFLINE`, every net scheduled or running on such a repeater is `CANCELLED`, and every member who checked in to one of those nets has their readiness recomputed, because a cancelled net's check-ins stop counting in both readiness variants. When an activation is demobilized or cancelled, its roster resolves in two branches: confirmed entries are released and volunteered entries are withdrawn, after which the activation's staffing figures are recomputed. When a member returns equipment damaged or a loan is written off as lost, the member's equipment privilege is suspended, their readiness score is recomputed with the privilege penalty, and — if the score drop flips their tier to `INELIGIBLE` — every live roster entry they hold is withdrawn. Each cascade hop is a real mutation on the touched resource, refreshing `updated_at` and incrementing `version` on it.

Referential integrity is validated left-to-right on every request: path identifiers first, in path order, then body foreign keys in their declared order. The first identifier that does not resolve to an existing resource rejects the whole request with `ERR_NOT_FOUND` before any business rule runs.

### 2.7. License Classes and Credential Ordinality

FCC license classes are ordinal credentials, ranked `TECHNICIAN` below `GENERAL` below `EXTRA`. The same three-value set is reused wherever a credential level is named: a member's `license_class`, a net's `min_license_class`, and an exam candidate's `element`. Any rule that compares classes uses ordinal comparison — "at least `GENERAL`" means `GENERAL` or `EXTRA`. Separately from class, a member's license has an expiry instant, `license_expires_at`; an actor whose license expiry is at or before the current logical-clock reading is treated as expired and rejected with `ERR_LICENSE_EXPIRED`, while an actor whose class is below a required minimum is rejected with `ERR_LICENSE_CLASS_INSUFFICIENT`.

### 2.8. Scores, Fees, and Numeric Precision

Readiness scores, drill scores, and field day points are integers. The member readiness score is computed from weighted components and rounded half-up to a whole number exactly once, after all components — check-in component, drill component, no-show bonus, and privilege penalty — have been summed; components are never pre-rounded, and the final score is floored at zero. All monetary amounts (dues, declared equipment values, late fees) are integer cents. The equipment late fee uses a pinned two-component nested rounding: each fee component is individually rounded half-up to whole cents first, the rounded components are then summed, and the cap against the item's declared value is applied last; summing unrounded components and rounding once is a different, non-conformant algorithm. Message handling durations are whole seconds. Dues arithmetic is calendrical: one renewal period is one calendar year (same month and day, with February 29 clamping to February 28 in non-leap target years), and amounts are integer cents.

### 2.9. Optimistic Concurrency Control

Two creation endpoints participate in optimistic concurrency control, because each legitimately supersedes a sibling resource and therefore must refuse to act on a stale view of the parent.

A `POST /coordination-requests` request must carry `expected_repeater_version` equal to the target repeater's current `version` as last observed by the client. Filing a new coordination request withdraws any existing `DRAFT` or `SUBMITTED` request for the same repeater and itself bumps the repeater's `version`, so a client holding an out-of-date version would silently supersede requests it never saw. If the supplied value does not match the repeater's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

A `POST /emergency-activations` request must carry `expected_served_agency_agreement_version` equal to the target served-agency agreement's current `version` as last observed by the client. Opening a new `STANDBY` activation cancels the prior `STANDBY` activation under the same agreement and bumps the agreement's `version`. If the supplied value does not match the agreement's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field; requests to any other resource must not include one. Within a request, the stale-version check is evaluated after the referenced entity's existence is resolved and before the endpoint's other business rules run.

### 2.10. Request Validation Order

Every request is screened in a fixed priority order, and a failure at any step masks all later checks — the reported error is always the earliest applicable one. First, authentication: the presence and validity of `X-User-ID` and `X-User-Role` (failures are `ERR_UNAUTHENTICATED`). Second, authorization: the caller's role against the endpoint's role list, including the declared ownership sub-checks (failures are `ERR_FORBIDDEN`). Third, existence: path and body references resolved left-to-right (failures are `ERR_NOT_FOUND`). Fourth, the from-state of the primary resource for the requested transition — generic invalid-from rejections are `ERR_INVALID_STATE`, and this step also covers the domain state errors such as `ERR_NET_NOT_OPEN`, `ERR_NET_WINDOW_NOT_STARTED`, `ERR_DRILL_NOT_IN_PROGRESS`, `ERR_MESSAGE_NOT_RELAYED`, `ERR_EVENT_NOT_OPEN`, `ERR_EVENT_FINALIZED`, `ERR_CANDIDATE_NOT_CHECKED_IN`, `ERR_ACTIVATION_NOT_OPEN`, `ERR_LOAN_NOT_OUTSTANDING`, and `ERR_CANDIDATES_PENDING`. Fifth, segregation of duties (`ERR_SOD_DEMOBILIZE`, `ERR_SOD_EXAM_GRADING`). Sixth, field-domain and structural rules: uniqueness, license class and expiry, frequency bands, traffic consistency, duplicate participation, loan windows, and operator-count caps. Seventh, temporal interval rules: net scheduling overlaps and site-lease window overlaps. Eighth, the state of referenced entities: active membership, equipment privilege standing, readiness tier, agreement and site status, coordination grants, and dues currency. Ninth and last, capacity and quota checks: roster fullness and exam session fullness.

When an endpoint's declared ownership sub-check inspects the resource named in the path (for example, returning a loan or acting on one's own net), that sub-check is evaluated after the path resource has been successfully resolved, so a nonexistent path identifier reports `ERR_NOT_FOUND` rather than `ERR_FORBIDDEN`.

Independently of this business-rule ordering, a structurally malformed request body — a missing required field, a wrong-typed value, an enum value outside its declared set, or an unknown or read-only field supplied by the client — is rejected with `ERR_VALIDATION`.

## 3. Business Logic & Workflows

### 3.1. Membership, Dues, and Member Readiness

A `ClubAdmin` registers a new member with a `callsign`, `full_name`, `license_class`, and `license_expires_at`. The callsign is unique club-wide and compared case-insensitively; a duplicate registration is rejected with `ERR_CALLSIGN_TAKEN`. New members start in `membership_status` `PENDING`: they hold no active standing until dues are paid. Their readiness fields are initialized by the same formula used everywhere else — zero check-ins and zero drills contribute nothing, but the no-show-free bonus still applies, so a brand-new member's `readiness_score` and `readiness_score_optimistic` both evaluate to 20 and their `readiness_tier` is `INELIGIBLE` until participation accrues. Their `equipment_privilege` starts at `GOOD_STANDING`.

Dues are administered through renewal. A renewal payload carries `periods`, which must be at least one. The paid-through instant is computed as the later of the current logical clock and the member's existing `dues_paid_through` (treated as the epoch `1970-01-01T00:00:00Z` when none has ever been set), extended by `periods` calendar years (same month and day, with February 29 clamping to February 28 in non-leap target years), and stored back as the new `dues_paid_through`. The response also reports `renewal_amount_cents`, which is `periods` times the annual dues of 3600 cents and is carried as an extra field on the returned member object. Renewal moves a `PENDING` or `LAPSED` member to `ACTIVE`; a member who is already `ACTIVE` renews in place as a self-loop, simply extending the paid-through window. Renewal of a `SUSPENDED` member is rejected with `ERR_INVALID_STATE`. Every renewal bumps the member's `version` and, except for the active self-loop, triggers a readiness recomputation. A member whose dues window expires lapses automatically: when the logical clock advances past `dues_paid_through`, the member transitions `ACTIVE` → `LAPSED` with readiness recomputed.

A `ClubAdmin` may also suspend an `ACTIVE` member (`ACTIVE` → `SUSPENDED`) and later reinstate them (`SUSPENDED` → `ACTIVE`). Like every status-driving operation in the API, these requests name their target state in a `to` field carried in the request body. Reinstatement requires that the member's dues are still current — `dues_paid_through` strictly later than the current clock — otherwise the request is rejected with `ERR_DUES_LAPSED`. Both transitions recompute readiness. Profile maintenance is a separate operation: an administrator may update `full_name`, `license_class`, or `license_expires_at` in place, which bumps `version` without any status change. The member directory can be listed with optional `membership_status` and `readiness_tier` filters alongside `limit` and `offset`.

**Readiness scoring.** Two scores are maintained per member. The trailing participation window is the closed interval from exactly 365 days before the current logical-clock reading through the present — a check-in or drill falling exactly on the window's opening instant counts. The verified score, stored as `readiness_score`, counts only confirmed participation: check-ins the member made on nets that have reached `CLOSED` with `checked_in_at` inside the trailing 365 days of the logical clock (tracked as `check_ins_12m_count`), and drills that have reached `COMPLETED` with `scheduled_start` inside the trailing 365 days in which the member originated at least one message that reached `RELAYED` or `DELIVERED` (tracked as `drills_12m_count`). The optimistic score, stored as `readiness_score_optimistic`, is identical except that nets in either `OPEN` or `CLOSED` count and drills in either `IN_PROGRESS` or `COMPLETED` count; it is informational only and never gates anything. Both variants share the same no-show input: `no_shows_12m_count` counts the member's roster entries in `NO_SHOW` whose `updated_at` falls inside the trailing 365 days.

The score itself is assembled from components. The check-in component is the qualifying check-in count divided by six, capped at one. The drill component is the qualifying drill count divided by two, capped at one. A member with zero no-shows in the window earns a flat bonus of 20; any no-show forfeits it entirely. A member whose `equipment_privilege` is `SUSPENDED` takes a flat penalty of 50. The score is fifty times the check-in component, plus thirty times the drill component, plus the bonus, minus the penalty — the total rounded half-up to a whole number in a single final rounding, then floored at zero. The tier follows: `ELIGIBLE` at a score of 70 or higher, `PROVISIONAL` at 40 or higher but below 70, and `INELIGIBLE` below 40. Readiness is recomputed on every event that moves an input: check-in creation, a net closing or being cancelled (for every checked-in member), a drill completing (for every participant), a roster entry being marked `NO_SHOW`, membership renewal, suspension, reinstatement, or lapse, and the equipment-privilege changes of §3.8.

### 3.2. Antenna Sites, Repeaters, and Frequency Coordination

**Site agreements.** Before a repeater may be installed, the club secures an antenna site agreement. A `ClubAdmin` creates one with `site_name`, `owner_name`, `lease_start`, and `lease_end`; it begins in `status` `NEGOTIATION` with `renewal_count` at zero. The lease window is a *closed* interval: both endpoints are inclusive, so one agreement's `lease_end` falling exactly on another's `lease_start` counts as an overlap. Two agreements for the same `site_name` may not have overlapping windows while both are in `NEGOTIATION` or `ACTIVE`; a violation is rejected with `ERR_SITE_WINDOW_CONFLICT`. This check applies at creation, at activation, and at renewal.

Activating an agreement (`NEGOTIATION` → `ACTIVE`) requires that `lease_end` still lies strictly in the future; otherwise the request is rejected with `ERR_INVALID_STATE`. Once the clock passes `lease_end`, the system transitions the agreement `ACTIVE` → `EXPIRED` and fires the infrastructure cascade of §2.6. An administrator may terminate an agreement from `NEGOTIATION` or from `ACTIVE`, transitioning it to `TERMINATED`; termination from `ACTIVE` fires the same three-hop cascade as expiry — every repeater referencing the agreement through `site_agreement_id` that is not already `OFFLINE` goes `OFFLINE`, every net on such a repeater in `SCHEDULED` or `OPEN` is `CANCELLED`, and every member with a check-in on a cancelled net has readiness recomputed. Termination from `NEGOTIATION` touches nothing downstream. `TERMINATED` is terminal. An expired agreement can be brought back to the table: the renewal transition `EXPIRED` → `NEGOTIATION` requires fresh `lease_start` and `lease_end` values in the request, requires the new `lease_end` to be strictly in the future, re-runs the closed-interval overlap check, replaces both stored lease fields, and increments `renewal_count` by one. Agreements can be listed with `status` and `site_name` filters.

**Repeaters.** A `ClubAdmin` registers a repeater with its `callsign` (unique club-wide; duplicates rejected with `ERR_REPEATER_CALLSIGN_TAKEN`), its `output_frequency_mhz`, and the `site_agreement_id` of the authorizing site agreement. A new repeater starts in `MAINTENANCE`. Bringing a repeater to `OPERATIONAL` — from `MAINTENANCE` or from `DEGRADED` — is gated twice: the site agreement must currently be `ACTIVE` (otherwise `ERR_SITE_AGREEMENT_INACTIVE`), and at least one coordination request for this repeater must have reached `GRANTED` (otherwise `ERR_NO_COORDINATION_GRANT`). From `OPERATIONAL` a repeater may be moved to `DEGRADED`, to `MAINTENANCE`, or to `OFFLINE`; from `DEGRADED` it may go to `MAINTENANCE` or `OFFLINE`; from `MAINTENANCE` it may be moved to `OFFLINE`; and from `OFFLINE` it may be returned to `MAINTENANCE`. Any transition into `OFFLINE` — whether ordered by an administrator or forced by the site cascade — cancels every net on that repeater in `SCHEDULED` or `OPEN` and recomputes the readiness of every member checked in to one of those nets. Repeaters can be listed with `status` and `site_agreement_id` filters.

**Frequency coordination.** Output frequencies are authorized by the regional frequency council, not by the club. A `ClubAdmin` files a coordination request naming the `repeater_id` and a `requested_frequency_mhz`; the request must also carry `expected_repeater_version` per §2.9. The proposed frequency must lie inside one of the two recognized amateur allocations — from 144.0 to 148.0 MHz inclusive, or from 420.0 to 450.0 MHz inclusive — otherwise the filing is rejected with `ERR_FREQUENCY_OUT_OF_BAND`. Filing a new request supersedes the repeater's paperwork: every existing request for the same repeater in `DRAFT` or `SUBMITTED` transitions to `WITHDRAWN`, and the repeater's `version` is bumped. The new request starts in `DRAFT` and can be listed with `repeater_id` and `status` filters.

Submission (`DRAFT` → `SUBMITTED`) stamps `submitted_at` with the current clock. Recording the council's decision moves a `SUBMITTED` request to `GRANTED` or `RETURNED` according to the supplied `outcome`, stores the supplied `council_reference`, and stamps `decision_at`. A `RETURNED` request re-enters `DRAFT` through the revision loop, which increments `revision_number` by one (the counter starts at 0 on a newly filed request) and, when a fresh `requested_frequency_mhz` is supplied, re-applies the band check to it (`ERR_FREQUENCY_OUT_OF_BAND` on a violation) before replacing the proposed frequency. A request in `DRAFT` or `SUBMITTED` may also be withdrawn outright, transitioning to `WITHDRAWN` — the same terminal state the supersede cascade uses. `GRANTED` and `WITHDRAWN` are terminal.

### 3.3. Net Operations and Check-In Logging

Nets are the club's recurring on-air meetings. Scheduling a net requires a `name`, the `repeater_id` it will run on, and a window given by `scheduled_start` and `scheduled_end`; an optional `min_license_class` (defaulting to `TECHNICIAN`) sets the credential floor, and an optional `net_control_member_id` lets a `ClubAdmin` designate the control operator. When a `NetControl` operator schedules the net, the control operator is always the caller: `net_control_member_id` is set from `X-User-ID` regardless of any supplied value. The designated control operator must hold a `license_class` ordinally at or above the net's `min_license_class` (else `ERR_LICENSE_CLASS_INSUFFICIENT`). Net windows are *half-open* — a net occupies from `scheduled_start` inclusive to `scheduled_end` exclusive — so two nets on the same repeater may not overlap while both are `SCHEDULED` or `OPEN`, but back-to-back nets whose boundary instants touch are explicitly allowed; a genuine conflict is rejected with `ERR_NET_TIME_CONFLICT`. A new net starts `SCHEDULED`. Nets can be listed with `repeater_id`, `net_control_member_id`, and `status` filters.

Opening a net (`SCHEDULED` → `OPEN`) is guarded three ways. The caller must be the net's control operator or a `ClubAdmin` (else `ERR_FORBIDDEN`); the current clock must sit inside the window — at or after `scheduled_start` and strictly before `scheduled_end` (else `ERR_NET_WINDOW_NOT_STARTED`); and the repeater must currently be `OPERATIONAL` (else `ERR_REPEATER_NOT_OPERATIONAL`). Closing a net (`OPEN` → `CLOSED`) requires the same caller rule and triggers two recomputations: the net's `checkin_count`, and the readiness of every checked-in member, whose participation now counts toward the verified score for the first time. A `SCHEDULED` net may be cancelled manually by its control operator or an administrator, and a net in `SCHEDULED` or `OPEN` is cancelled automatically when its repeater goes `OFFLINE`; either way, affected members' readiness is recomputed because a `CANCELLED` net feeds neither readiness variant. `CLOSED` and `CANCELLED` are terminal.

A member joins an open net by checking in with the target `net_session_id`; the recorded `member_id` is always the caller. Check-in is refused unless the net is currently `OPEN` (`ERR_NET_NOT_OPEN`), the caller's `membership_status` is `ACTIVE` (`ERR_MEMBERSHIP_NOT_ACTIVE`), and the caller's license satisfies the net's `min_license_class` and is unexpired. Each member may check in to a given net at most once (`ERR_ALREADY_CHECKED_IN`). Stations report formal traffic through `has_traffic` (defaulting to false) and `traffic_count` (defaulting to zero), and the two must agree: the check-in is rejected with `ERR_INVALID_TRAFFIC_COUNT` exactly when `has_traffic` differs from whether `traffic_count` is at least one — so `has_traffic` true requires `traffic_count` of at least one, while `has_traffic` false accepts any `traffic_count` below one, including a negative value. A successful check-in stamps `checked_in_at` from the clock, recomputes the net's `checkin_count`, and recomputes the member's readiness — the optimistic variant counts the participation immediately, while the verified variant waits for the net to close. Check-in records are immutable once written and can be listed with `net_session_id` and `member_id` filters.

### 3.4. Served-Agency Agreements, Emergency Activations, and Rosters

**Served-agency agreements.** Emergency work is performed under a written agreement with a served agency. A `ClubAdmin` creates one with `agency_name`, `max_operators` (the per-activation operator ceiling, which must be greater than zero), `effective_start`, and `effective_end`; it begins in `DRAFT` and can be listed with a `status` filter. Activation (`DRAFT` → `ACTIVE`) requires `effective_end` strictly in the future, failing with `ERR_INVALID_STATE` otherwise. When the clock passes `effective_end`, the system moves the agreement `ACTIVE` → `EXPIRED` and cancels every `STANDBY` activation under it, with the roster cascade of the paragraphs below. An administrator may terminate an agreement from `DRAFT` or from `ACTIVE`, moving it to `TERMINATED` — termination from `DRAFT` has no downstream effect, while termination from `ACTIVE` is blocked as long as any activation under the agreement is `ACTIVATED`, rejected with `ERR_ACTIVATION_IN_PROGRESS`, and otherwise cancels the agreement's `STANDBY` activations with their roster cascade. `EXPIRED` and `TERMINATED` are the agreement's terminal states.

**Activations.** An `EmergencyCoordinator` opens an activation against an existing agreement by supplying `agreement_id`, a `title`, the `required_operators` count, and `expected_served_agency_agreement_version` per §2.9. The referenced agreement must be in `DRAFT` or `ACTIVE` at creation time (else `ERR_AGREEMENT_NOT_ACTIVE`), and `required_operators` must be greater than zero and no greater than the agreement's `max_operators` (else `ERR_REQUIRED_OPERATORS_EXCEED_AGREEMENT`). Opening a new activation supersedes the old one: any prior `STANDBY` activation for the same agreement transitions to `CANCELLED` with the full roster cascade, and the agreement's `version` is bumped. The new activation begins in `STANDBY` and can be listed with `agreement_id`, `activated_by_member_id`, and `status` filters.

Moving an activation to `ACTIVATED` (`STANDBY` → `ACTIVATED`) requires the agreement to currently be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE` otherwise); the transition records the calling member as `activated_by_member_id` and stamps `activated_at`. Demobilization (`ACTIVATED` → `DEMOBILIZED`) is the system's first segregation-of-duties point: the member who demobilizes must not be the member recorded as `activated_by_member_id`, and a violation is rejected with `ERR_SOD_DEMOBILIZE`. Demobilization stamps `demobilized_at` and resolves the roster in two sibling branches — every `CONFIRMED` entry transitions to `RELEASED` and every `VOLUNTEERED` entry transitions to `WITHDRAWN` — after which the activation's `confirmed_count` and `staffing_posture` are recomputed. An activation in `STANDBY` may also be cancelled outright, manually or by the agreement and supersede cascades, with the same roster resolution and recomputation. `DEMOBILIZED` and `CANCELLED` are terminal.

**Rosters.** A member volunteers for an activation by naming its `activation_id`; the recorded `member_id` is the caller. Volunteering requires the activation to be in `STANDBY` or `ACTIVATED` (else `ERR_ACTIVATION_NOT_OPEN`), the member's `membership_status` to be `ACTIVE` (`ERR_MEMBERSHIP_NOT_ACTIVE`), and the member's `readiness_tier` to be anything but `INELIGIBLE` (`ERR_ROSTER_ENTRY_INELIGIBLE`). A member may hold at most one roster entry per activation, ever: an existing entry in any status — including a terminal one such as `WITHDRAWN` or `RELEASED` — blocks a fresh volunteer attempt (`ERR_ALREADY_ON_ROSTER`). New entries start `VOLUNTEERED` and can be listed with `activation_id`, `member_id`, and `status` filters.

Confirmation (`VOLUNTEERED` → `CONFIRMED`) is performed by an `EmergencyCoordinator` and enforces four conditions: the activation is in `STANDBY` or `ACTIVATED` (`ERR_INVALID_STATE` otherwise), the member is `ACTIVE` (`ERR_MEMBERSHIP_NOT_ACTIVE`), the member's tier is not `INELIGIBLE` (`ERR_ROSTER_ENTRY_INELIGIBLE`), and the activation is not yet full — its `confirmed_count` must be below `required_operators`, with a full roster rejected as `ERR_ROSTER_FULL`. Confirmation stamps `confirmed_at` from the clock. A mistaken confirmation can be reverted (`CONFIRMED` → `VOLUNTEERED`) while the activation remains in `STANDBY` or `ACTIVATED`, which nulls `confirmed_at`. A confirmed member may be released (`CONFIRMED` → `RELEASED`) under the same activation-state condition, or may be marked `NO_SHOW` (`CONFIRMED` → `NO_SHOW`) once the activation is `ACTIVATED` — the latter also recomputes the member's readiness, because the no-show lands in `no_shows_12m_count` and forfeits the no-show-free bonus for the following year. The volunteering member may withdraw their own entry (`VOLUNTEERED` → `WITHDRAWN`); a withdrawal attempt by anyone else is rejected with `ERR_FORBIDDEN`. Withdrawal also arrives by cascade: activation cancellation withdraws `VOLUNTEERED` entries, and a member whose tier flips to `INELIGIBLE` has every entry — `VOLUNTEERED` or `CONFIRMED` — on a live (`STANDBY` or `ACTIVATED`) activation withdrawn. `RELEASED`, `WITHDRAWN`, and `NO_SHOW` are terminal.

Staffing is a pure threshold over the roster. `confirmed_count` is the number of entries in `CONFIRMED`; `staffing_posture` reads `ADEQUATE` when `confirmed_count` is at least `required_operators` and `UNDERSTAFFED` otherwise. The boundary is inclusive — a count exactly equal to the requirement is adequate and simultaneously blocks any further confirmation with `ERR_ROSTER_FULL`. Both figures are recomputed on every transition into or out of `CONFIRMED`: confirmations, un-confirm reverts, releases, no-shows, and tier-flip withdrawals.

### 3.5. Drills and Radiogram Message Handling

Drills rehearse formal message traffic. An `EmergencyCoordinator` plans one with a `title`, a window from `scheduled_start` to `scheduled_end`, and an optional `passing_score` — the club's reference score for evaluation, defaulting to 70 on a zero-to-hundred scale; a `passing_score` outside 0–100 is rejected with `ERR_VALIDATION`. Drills can be listed with a `status` filter. A planned drill may be started (`PLANNED` → `IN_PROGRESS`) only once the clock has reached `scheduled_start` (else `ERR_INVALID_STATE`), and a running drill is completed (`IN_PROGRESS` → `COMPLETED`) when the exercise wraps; completion recomputes `drills_12m_count` and readiness for every member who originated at least one message that reached `RELAYED` or `DELIVERED`. A drill may be cancelled from `PLANNED` or `IN_PROGRESS`. `COMPLETED` and `CANCELLED` are terminal.

During a running drill, a member originates a radiogram by naming the `drill_id` and a `precedence` of `ROUTINE`, `PRIORITY`, or `EMERGENCY`; the caller is recorded as `originator_member_id` and the message begins in `ORIGINATED` with a `relay_count` of zero. Origination requires the drill to be `IN_PROGRESS` (`ERR_DRILL_NOT_IN_PROGRESS`) and the caller's membership to be `ACTIVE` (`ERR_MEMBERSHIP_NOT_ACTIVE`); messages can be listed with `drill_id`, `originator_member_id`, and `status` filters. Relaying moves a message `ORIGINATED` → `RELAYED`, and each subsequent relay is a `RELAYED` → `RELAYED` self-loop — every entry into `RELAYED`, self-loops included, adds one to `relay_count`. Both relay forms require the drill still `IN_PROGRESS` and the caller `ACTIVE`. Delivery (`RELAYED` → `DELIVERED`) is possible only for a message that has actually been relayed: a message that never left `ORIGINATED` — where `relay_count` is still zero — cannot be delivered and is rejected with `ERR_MESSAGE_NOT_RELAYED`. Delivery stamps `delivered_at` and computes `handling_seconds` as the whole-second difference between `delivered_at` and the message's `created_at`; both remain null until delivery. Unlike origination and relay, delivery does not re-check that the calling member's membership is `ACTIVE` — only the drill state and the message state gate it. A message in `ORIGINATED` or `RELAYED` may be cancelled — by its originator at any time, or by any member while the drill is still `IN_PROGRESS`; a non-originator attempting cancellation after the drill has moved on fails as `ERR_FORBIDDEN` or `ERR_INVALID_STATE` depending on which condition broke. `DELIVERED` and `CANCELLED` are terminal.

### 3.6. Field Day Events and Scoring

Field Day is the club's flagship operating event, and scoring runs live while contacts pour in. A `ClubAdmin` creates an event with a unique `name` (duplicates rejected with `ERR_EVENT_NAME_TAKEN`) and an operating period from `start_at` to `end_at`; the event starts in `PLANNING` with `contact_count`, `provisional_score`, and `final_score` all at zero. Events can be listed with a `status` filter. Opening the event (`PLANNING` → `OPEN`) requires the clock to sit within the operating period — no earlier than `start_at` and no later than `end_at` (else `ERR_INVALID_STATE`). Scoring (`OPEN` → `SCORING`) requires the clock to be strictly past `end_at`. Finalization (`SCORING` → `FINALIZED`) locks `final_score`, which is never recomputed afterwards; `FINALIZED` is terminal.

While an event is `OPEN`, a member logs a contact with the `event_id`, the `worked_callsign` of the station contacted, the `band`, the `mode`, and the `power_category`; the caller is recorded as `operator_member_id`. Logging is refused unless the event is `OPEN` (`ERR_EVENT_NOT_OPEN`) and the caller's membership is `ACTIVE`. The event's `contact_count` counts every logged contact, duplicates included. Contacts can be listed with `event_id`, `operator_member_id`, and `is_duplicate` filters; the `is_duplicate` filter is parsed case-insensitively — the literal values `true` and `false` select duplicate and non-duplicate contacts respectively, and any other value matches nothing, yielding an empty page.

Each contact's `points` are computed once at creation and are immutable afterwards. The base value comes from the mode: two points for `CW`, two for `DIGITAL`, one for `PHONE`. That base is multiplied by the power factor: five for `QRP`, two for `LOW`, one for `HIGH`. A band bonus of two points is added when the band is one of the VHF entries, `B6M` or `B2M`; the HF bands `B160M`, `B80M`, `B40M`, `B20M`, `B15M`, and `B10M` earn no bonus. The contact's points are the resulting total capped at ten.

Two event scores run in parallel. The `provisional_score` is optimistic: it sums the points of **all** of the event's contacts, duplicates included, and adds a 100-point bonus when the total contact count reaches 100. The `final_score` is strict: it sums only contacts whose `is_duplicate` flag is false and adds the same 100-point bonus when the count of non-duplicate contacts reaches 100. Both are recomputed live on every contact creation and on every duplicate-flag toggle while the event is not `FINALIZED`. A `ClubAdmin` toggles a contact's `is_duplicate` flag by supplying the new `is_duplicate` value; toggling leaves `provisional_score` unchanged by design — duplicates still count there — while `final_score` is recomputed. Once the event is `FINALIZED`, toggling is refused with `ERR_EVENT_FINALIZED`.

### 3.7. License Exam Session Administration

Volunteer-examiner sessions are administered by the `ExamLiaison` role. Scheduling a session requires a `location`, a `scheduled_at` start instant, and a `max_candidates` capacity greater than zero; the session begins `SCHEDULED` and can be listed with a `status` filter. The session may be opened (`SCHEDULED` → `IN_PROGRESS`) only once the clock has reached `scheduled_at` (else `ERR_INVALID_STATE`). Closing a session (`IN_PROGRESS` → `CLOSED`) is blocked while any candidate remains non-terminal — every candidate must be in `PASSED`, `FAILED`, `NO_SHOW`, or `CANCELLED`, and a violation is rejected with `ERR_CANDIDATES_PENDING`. Cancelling a session from `SCHEDULED` or `IN_PROGRESS` cascades every candidate still in `REGISTERED` or `CHECKED_IN` to `CANCELLED`. `CLOSED` and `CANCELLED` are terminal.

Candidates need not be club members. Registration names the `session_id`, the `candidate_name`, the candidate's FCC Registration Number `frn`, the exam `element` attempted (`TECHNICIAN`, `GENERAL`, or `EXTRA`), and an optional `member_id` linking the candidate to a club member. Registration is accepted only while the session is `SCHEDULED` — against a session in any other status the attempt is rejected with `ERR_INVALID_STATE` — is refused at capacity — when `registered_count` has reached `max_candidates`, the rejection is `ERR_SESSION_FULL` — and enforces one FRN per session, with a duplicate rejected as `ERR_DUPLICATE_CANDIDATE_FRN`. The FRN uniqueness check spans every candidate of the session regardless of status, so an FRN held by a `NO_SHOW` or `CANCELLED` candidate still blocks re-registration. `registered_count` itself counts candidates in `REGISTERED` or `CHECKED_IN` and is recomputed as registrations and terminal transitions occur. Candidates can be listed with `session_id`, `member_id`, `checked_in_by_member_id`, and `status` filters.

On session day, the liaison checks a `REGISTERED` candidate in (`REGISTERED` → `CHECKED_IN`) while the session is `IN_PROGRESS` (`ERR_INVALID_STATE` otherwise), and the system records the caller as `checked_in_by_member_id`. A candidate who never appears is marked `NO_SHOW` (`REGISTERED` → `NO_SHOW`), likewise only while the session is `IN_PROGRESS`. Result recording is the second segregation-of-duties point: the member recording a result must differ from the member recorded as `checked_in_by_member_id`, with a violation rejected as `ERR_SOD_EXAM_GRADING`. Recording requires the session still `IN_PROGRESS` and the candidate in `CHECKED_IN` — recording against a candidate in any other state is rejected with `ERR_CANDIDATE_NOT_CHECKED_IN`. The supplied `score_percent`, an integer from zero to one hundred, decides the outcome: 74 or higher records `PASSED`, anything below records `FAILED`.

A pass carries a real credential consequence when the candidate is linked to a club member. If the passed `element` is ordinally strictly higher than the member's current `license_class`, the member's `license_class` is upgraded to that element; either way on a pass the member's `license_expires_at` is set to the current clock plus 3650 days, and the member's `version` is bumped. A candidate record carries its `session_id`, its `frn`, its attempted `element`, the optional `member_id` link, the `score_percent` once recorded, and its `status`; `PASSED`, `FAILED`, `NO_SHOW`, and `CANCELLED` are terminal.

### 3.8. Equipment Loans and the Privilege Cascade

The club lends equipment to members in good standing. A loan names an `item_tag`, a `due_at` return deadline, and an `estimated_value_cents` declared replacement value greater than zero. A `Member` borrower creates their own loan — the recorded `member_id` is always the caller and any `member_id` supplied in the body is ignored — while a `ClubAdmin` may create a loan for any member and must supply `member_id` (omitting it is rejected with `ERR_VALIDATION`). The window rule is strict: `due_at` must lie strictly after the current clock and no more than 90 days in the future (else `ERR_LOAN_WINDOW_INVALID`). The borrower must be `ACTIVE` (`ERR_MEMBERSHIP_NOT_ACTIVE`) and hold `equipment_privilege` `GOOD_STANDING` (`ERR_EQUIPMENT_PRIVILEGE_SUSPENDED`). At most one outstanding loan — status `ACTIVE` or `OVERDUE` — may exist per `item_tag`; a second checkout of the same tag is rejected with `ERR_ITEM_ON_LOAN`. A new loan starts `ACTIVE` with `checked_out_at` stamped from the clock, and loans can be listed with `member_id`, `item_tag`, and `status` filters.

When the clock passes `due_at`, an `ACTIVE` loan becomes `OVERDUE` automatically. Return accepts a `return_condition` of `GOOD` or `DAMAGED` and may be performed by the borrower or a `ClubAdmin` (anyone else is `ERR_FORBIDDEN`); return or write-off against a loan that is not outstanding — neither `ACTIVE` nor `OVERDUE` — is rejected with `ERR_LOAN_NOT_OUTSTANDING`. A return stamps `returned_at` and settles `late_fee_cents`, which is zero while a loan is outstanding.

The late fee follows a pinned computation. A loan marked lost is priced at its full declared value: `late_fee_cents` equals `estimated_value_cents`, and no further arithmetic applies. A loan returned at or before `due_at` owes no lateness component, though an on-time return marked `DAMAGED` still owes the damage component described below. For a late return, the days overdue are the elapsed time from `due_at` to `returned_at` divided into days and rounded up to a whole day; the base fee is that day count times 150 cents per day, rounded half-up to whole cents. When the `return_condition` is `DAMAGED`, a damage fee of one tenth of the declared value — ten percent of `estimated_value_cents`, itself rounded half-up to whole cents — is computed. The two rounded components are summed, and the total is capped at `estimated_value_cents`; the cap is applied last, after rounding and summation.

Condition drives consequences beyond money. A `DAMAGED` return — and equally a mark-lost write-off, a `ClubAdmin` action available from `ACTIVE` or `OVERDUE` — suspends the member's `equipment_privilege` (`GOOD_STANDING` → `SUSPENDED`), bumps the member's `version`, and recomputes readiness with the 50-point privilege penalty now applied. If that recomputation flips the member's `readiness_tier` to `INELIGIBLE`, the roster cascade fires: every roster entry the member holds on a live (`STANDBY` or `ACTIVATED`) activation is withdrawn — `VOLUNTEERED` entries and `CONFIRMED` entries alike — and each `CONFIRMED` withdrawal recomputes its activation's `confirmed_count` and `staffing_posture`. `RETURNED` and `LOST` are terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — status transitions, renewals, decisions, returns — return `200 OK`. Detail and list retrievals return `200 OK`. The complete request and response shapes for each operation are defined by the workflows in §3; this table is a navigational index only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/members` | Register a club member (starts `PENDING`) | ClubAdmin |
| GET | `/members` | List members | ClubAdmin, EmergencyCoordinator, NetControl, ExamLiaison |
| GET | `/members/{id}` | Member detail including computed readiness fields | ClubAdmin, Member, EmergencyCoordinator, NetControl, ExamLiaison |
| PATCH | `/members/{id}` | Update mutable member profile fields | ClubAdmin |
| POST | `/members/{id}/set-status` | Suspend or reinstate a member | ClubAdmin |
| POST | `/members/{id}/renew` | Pay dues and extend `dues_paid_through` | ClubAdmin |
| POST | `/antenna-site-agreements` | Create a site agreement in `NEGOTIATION` | ClubAdmin |
| GET | `/antenna-site-agreements` | List site agreements | ClubAdmin |
| GET | `/antenna-site-agreements/{id}` | Site agreement detail | ClubAdmin |
| POST | `/antenna-site-agreements/{id}/set-status` | Activate, terminate, or renew an expired agreement | ClubAdmin |
| POST | `/repeaters` | Register a repeater (starts `MAINTENANCE`) | ClubAdmin |
| GET | `/repeaters` | List repeaters | ClubAdmin, NetControl, Member |
| GET | `/repeaters/{id}` | Repeater detail | ClubAdmin, NetControl, Member |
| POST | `/repeaters/{id}/set-status` | Move a repeater between `OPERATIONAL`, `DEGRADED`, `MAINTENANCE`, `OFFLINE` | ClubAdmin |
| POST | `/coordination-requests` | File a frequency-coordination request for a repeater (supersedes existing drafts; OCC) | ClubAdmin |
| GET | `/coordination-requests` | List coordination requests | ClubAdmin |
| GET | `/coordination-requests/{id}` | Coordination request detail | ClubAdmin |
| POST | `/coordination-requests/{id}/submit` | Submit a draft request to the council | ClubAdmin |
| POST | `/coordination-requests/{id}/record-decision` | Record the council decision (`GRANTED` or `RETURNED`) | ClubAdmin |
| POST | `/coordination-requests/{id}/revise` | Revise a returned request back to `DRAFT` | ClubAdmin |
| POST | `/coordination-requests/{id}/withdraw` | Withdraw a draft or submitted request | ClubAdmin |
| POST | `/net-sessions` | Schedule a net on a repeater | NetControl, ClubAdmin |
| GET | `/net-sessions` | List nets | ClubAdmin, NetControl, Member |
| GET | `/net-sessions/{id}` | Net detail including `checkin_count` | ClubAdmin, NetControl, Member |
| POST | `/net-sessions/{id}/set-status` | Open, close, or cancel a net | NetControl, ClubAdmin |
| POST | `/check-ins` | Member checks in to an open net | Member |
| GET | `/check-ins` | List check-ins | ClubAdmin, NetControl, Member |
| GET | `/check-ins/{id}` | Check-in detail | ClubAdmin, NetControl, Member |
| POST | `/served-agency-agreements` | Create a served-agency agreement in `DRAFT` | ClubAdmin |
| GET | `/served-agency-agreements` | List served-agency agreements | ClubAdmin, EmergencyCoordinator |
| GET | `/served-agency-agreements/{id}` | Served-agency agreement detail | ClubAdmin, EmergencyCoordinator |
| POST | `/served-agency-agreements/{id}/set-status` | Activate or terminate an agreement | ClubAdmin |
| POST | `/emergency-activations` | Open a `STANDBY` activation under an agreement (supersedes prior standby; OCC) | EmergencyCoordinator |
| GET | `/emergency-activations` | List activations | ClubAdmin, EmergencyCoordinator, Member |
| GET | `/emergency-activations/{id}` | Activation detail including `confirmed_count` and `staffing_posture` | ClubAdmin, EmergencyCoordinator, Member |
| POST | `/emergency-activations/{id}/set-status` | Activate, demobilize, or cancel an activation | EmergencyCoordinator |
| POST | `/roster-entries` | Member volunteers for an activation | Member |
| GET | `/roster-entries` | List roster entries | ClubAdmin, EmergencyCoordinator, Member |
| GET | `/roster-entries/{id}` | Roster entry detail | ClubAdmin, EmergencyCoordinator, Member |
| POST | `/roster-entries/{id}/set-status` | Confirm, revert, release, no-show (EC); withdraw (self) | EmergencyCoordinator, Member |
| POST | `/drills` | Plan a drill | EmergencyCoordinator |
| GET | `/drills` | List drills | ClubAdmin, EmergencyCoordinator, Member |
| GET | `/drills/{id}` | Drill detail | ClubAdmin, EmergencyCoordinator, Member |
| POST | `/drills/{id}/set-status` | Start, complete, or cancel a drill | EmergencyCoordinator |
| POST | `/drill-messages` | Originate a radiogram in a running drill | Member |
| GET | `/drill-messages` | List drill messages | ClubAdmin, EmergencyCoordinator, Member |
| GET | `/drill-messages/{id}` | Drill message detail | ClubAdmin, EmergencyCoordinator, Member |
| POST | `/drill-messages/{id}/set-status` | Relay, deliver, or cancel a message | Member |
| POST | `/field-day-events` | Create a field day event in `PLANNING` | ClubAdmin |
| GET | `/field-day-events` | List field day events | ClubAdmin, Member |
| GET | `/field-day-events/{id}` | Event detail including scores | ClubAdmin, Member |
| POST | `/field-day-events/{id}/set-status` | Open, move to scoring, or finalize an event | ClubAdmin |
| POST | `/field-day-contacts` | Log a contact while the event is `OPEN` | Member |
| GET | `/field-day-contacts` | List contacts | ClubAdmin, Member |
| GET | `/field-day-contacts/{id}` | Contact detail | ClubAdmin, Member |
| POST | `/field-day-contacts/{id}/set-duplicate` | Toggle a contact's duplicate flag | ClubAdmin |
| POST | `/exam-sessions` | Schedule a license exam session | ExamLiaison |
| GET | `/exam-sessions` | List exam sessions | ClubAdmin, ExamLiaison |
| GET | `/exam-sessions/{id}` | Exam session detail including `registered_count` | ClubAdmin, ExamLiaison |
| POST | `/exam-sessions/{id}/set-status` | Open, close, or cancel a session | ExamLiaison |
| POST | `/exam-candidates` | Register a candidate for a session | ExamLiaison |
| GET | `/exam-candidates` | List exam candidates | ClubAdmin, ExamLiaison |
| GET | `/exam-candidates/{id}` | Exam candidate detail | ClubAdmin, ExamLiaison |
| POST | `/exam-candidates/{id}/check-in` | Check a candidate in | ExamLiaison |
| POST | `/exam-candidates/{id}/record-result` | Record a pass/fail result | ExamLiaison |
| POST | `/exam-candidates/{id}/mark-no-show` | Mark a registered candidate as no-show | ExamLiaison |
| POST | `/equipment-loans` | Check out equipment to a member | Member, ClubAdmin |
| GET | `/equipment-loans` | List equipment loans | ClubAdmin, Member |
| GET | `/equipment-loans/{id}` | Loan detail including `late_fee_cents` | ClubAdmin, Member |
| POST | `/equipment-loans/{id}/return` | Return a loan and settle fees | Member, ClubAdmin |
| POST | `/equipment-loans/{id}/mark-lost` | Write off a loan as lost | ClubAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving capability) | ClubAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is an index of identifiers to HTTP status codes only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CALLSIGN_TAKEN` | 409 |
| `ERR_REPEATER_CALLSIGN_TAKEN` | 409 |
| `ERR_EVENT_NAME_TAKEN` | 409 |
| `ERR_MEMBERSHIP_NOT_ACTIVE` | 409 |
| `ERR_DUES_LAPSED` | 409 |
| `ERR_LICENSE_CLASS_INSUFFICIENT` | 422 |
| `ERR_LICENSE_EXPIRED` | 422 |
| `ERR_ALREADY_CHECKED_IN` | 409 |
| `ERR_INVALID_TRAFFIC_COUNT` | 422 |
| `ERR_NET_NOT_OPEN` | 409 |
| `ERR_NET_WINDOW_NOT_STARTED` | 409 |
| `ERR_NET_TIME_CONFLICT` | 409 |
| `ERR_REPEATER_NOT_OPERATIONAL` | 409 |
| `ERR_FREQUENCY_OUT_OF_BAND` | 422 |
| `ERR_NO_COORDINATION_GRANT` | 409 |
| `ERR_SITE_AGREEMENT_INACTIVE` | 409 |
| `ERR_SITE_WINDOW_CONFLICT` | 409 |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 |
| `ERR_ACTIVATION_IN_PROGRESS` | 409 |
| `ERR_ACTIVATION_NOT_OPEN` | 409 |
| `ERR_REQUIRED_OPERATORS_EXCEED_AGREEMENT` | 422 |
| `ERR_SOD_DEMOBILIZE` | 403 |
| `ERR_SOD_EXAM_GRADING` | 403 |
| `ERR_ROSTER_FULL` | 409 |
| `ERR_ROSTER_ENTRY_INELIGIBLE` | 409 |
| `ERR_ALREADY_ON_ROSTER` | 409 |
| `ERR_DRILL_NOT_IN_PROGRESS` | 409 |
| `ERR_MESSAGE_NOT_RELAYED` | 409 |
| `ERR_EVENT_NOT_OPEN` | 409 |
| `ERR_EVENT_FINALIZED` | 409 |
| `ERR_SESSION_FULL` | 409 |
| `ERR_CANDIDATES_PENDING` | 409 |
| `ERR_CANDIDATE_NOT_CHECKED_IN` | 409 |
| `ERR_DUPLICATE_CANDIDATE_FRN` | 409 |
| `ERR_ITEM_ON_LOAN` | 409 |
| `ERR_EQUIPMENT_PRIVILEGE_SUSPENDED` | 409 |
| `ERR_LOAN_WINDOW_INVALID` | 422 |
| `ERR_LOAN_NOT_OUTSTANDING` | 409 |
