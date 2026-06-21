# Itsm-Helpdesk API — Product Requirements Document

## 1. Introduction

Modern IT operations live or die by how predictably an organization can absorb, triage, and close out service interruptions. This document specifies the backend API for an **IT Service Management (ITSM) Helpdesk** platform that takes an incident from the moment a requester first reports it, through triage and agent work, optional change-control gating, problem and known-error investigation, and finally to resolution, satisfaction measurement, and closure. The platform exists to make two promises auditable at all times: that every ticket is governed by an explicit Service Level Agreement (SLA) clock with a defensible response and resolution deadline, and that every potentially disruptive change is approved by the right people — and never self-approved — before it touches a live configuration item.

Several distinct concerns are deliberately woven together here. Tickets carry **two independent state dimensions at once**: a lifecycle axis (is the ticket new, being worked, on hold, resolved, closed) and an SLA axis (is the clock running, paused, breached, or met) that evolves on its own schedule. Change requests fan out to a Change Advisory Board (CAB) whose members vote to approve or reject, with quorum sized to the change's risk and a hard segregation-of-duties rule preventing the person who raised a change from voting on it. Problems group repeating incidents under a single root cause, optionally flag the failing asset as degraded, and graduate to published known errors that feed knowledge-base deflection so future requesters can self-serve before a ticket is ever created. A test-driving clock lets evaluators move time forward deterministically so that SLA breaches and time windows can be exercised without waiting on the wall clock.

Because the platform is the system of record for compliance reporting, every computed figure — SLA due dates, paused-time credits, CAB tallies, queue load scores, and the CSAT index — must be reproducible to the digit. The sections that follow fix the contract precisely where ambiguity would break interoperability, and describe the business workflows in enough narrative detail that an implementer can reconstruct each rule without guessing.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request that mutates state, and most reads, is authenticated by two HTTP headers: `X-User-ID`, an opaque identifier for the calling principal, and `X-User-Role`, naming the caller's role. When either header is missing on an endpoint that requires authentication, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403). Opening a ticket is the one creation operation that tolerates an anonymous caller, and GET reads do not require authentication.

There are exactly five roles, spelled precisely as follows: `Requester`, `Agent`, `ChangeManager`, `CabMember`, and `PlatformAdmin`.

- A `Requester` is the end user who reports incidents. They open tickets, accept knowledge-base deflection, and — on their own tickets only — reopen a resolved ticket, cancel a new one, and submit a satisfaction survey.
- An `Agent` is the service-desk or fulfilment engineer who works tickets and drives problem investigations, known errors, and knowledge-base content.
- A `ChangeManager` raises change requests, submits them to the CAB, and marks approved changes implemented or failed.
- A `CabMember` votes on submitted changes.
- A `PlatformAdmin` configures categories, SLA policies, assignment groups, and assets, and operates the test-driving clock.

All five roles use an **opaque** identity model. When `X-User-Role` is `Requester`, `X-User-ID` is an opaque requester identifier not tied to any persisted entity row of its own; the server records it on the ticket as `requester_id` at open time, and ownership-sensitive operations (reopen, cancel, survey) compare the stored `requester_id` to the caller's `X-User-ID` rather than to any entity's `id`. When `X-User-Role` is `Agent`, `X-User-ID` is an opaque agent identifier the server may record as `assignee_user_id` on a ticket or as `owner_user_id` on a problem, but never compares to an entity `id`. When `X-User-Role` is `ChangeManager`, `X-User-ID` is an opaque manager identifier recorded as `raised_by_user_id` on the change the manager raises. When `X-User-Role` is `CabMember`, `X-User-ID` is an opaque board-member identifier recorded as `voter_user_id` on each vote the member casts. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier the server may log but does not tie to any entity `id`.

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

All list endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; a request asking for more than 100 items is clamped to 100 and one asking for fewer than 1 is clamped up to 1. The `offset` parameter defaults to 0 and counts from the start of the result set; a negative `offset` is clamped to 0. A `limit` or `offset` that is present but not parseable as an integer is rejected with `ERR_VALIDATION`. List results are ordered by `created_at` ascending, so the oldest matching resource appears first. The pagination fields reported in the `meta` object are `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of resources matching the query before the page window is applied and `has_more` is true when the window does not reach the end of the result set.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries a server-minted `id`, a UUID with no type prefix, generated by the platform and never supplied by the client. Most resources additionally carry a `created_at` and an `updated_at` timestamp, both ISO 8601 UTC with three fractional digits, and an integer `version` that begins at 1 and increments by exactly one on every successful mutation of that resource. The `created_at` value is fixed at creation and never changes; `updated_at` is refreshed on every mutation.

There is one deliberate exception. The CAB vote is an append-only event record: a `CabVote` carries only `id` and `created_at`. It has no `updated_at` and no `version`, because a cast vote is immutable once recorded. Every other resource — `Category`, `SlaPolicy`, `AssignmentGroup`, `Ticket`, `Problem`, `KnownError`, `KbArticle`, `ChangeRequest`, `CsatSurvey`, and `Asset` — carries the full `created_at`, `updated_at`, and `version` triple.

### 2.5. Nested Resource Retrieval and Foreign-Key Resolution

Several read paths address a child collection through its parent, for example the votes belonging to a change request, the known errors documented under a problem, the surveys filed against a ticket, or the tickets linked to an asset. Path parameters are validated strictly left to right: the parent identifier is resolved first, and if it does not name an existing resource the request fails with `ERR_NOT_FOUND` (HTTP 404) before any child lookup is attempted. The same `ERR_NOT_FOUND` governs any `/{id}` path whose target does not exist.

Foreign keys supplied in a request body are a separate concern from path resolution. Whenever a create or link operation carries a reference — a `category_id`, `sla_policy_id`, `assignment_group_id`, `ticket_id`, `change_request_id`, `problem_id`, `asset_id`, or `kb_article_id` — the referenced resource must already exist, or the request is rejected with `ERR_FK_NOT_FOUND` (HTTP 404).

### 2.6. Computed Fields, Cascades, and Consistency

Many fields are not supplied by clients but derived by the server and kept continuously consistent. Counters such as a group's `queue_depth`, a problem's `linked_ticket_count`, an asset's `open_incident_count`, a change's `approve_count` and `reject_count`, and an article's `view_count` and `deflection_count` are recomputed from their underlying records rather than blindly incremented, so they always reflect the true current set. A `Ticket` exposes both its `lifecycle_state` and its independently evolving `sla_state`; an `Asset` exposes a derived `status`; a `Problem` and a `ChangeRequest` each expose their own derived `state`.

When one operation changes more than one resource, every affected resource has its `updated_at` refreshed and its `version` incremented. These cross-resource cascades — a vote that resumes a paused ticket, a root-cause finding that degrades an asset, a resolution that decrements a problem's linked count — are described in full within the workflow narratives of §3, because the secondary effects, not just the primary transition, are part of the contract.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control (OCC), because each re-derives state from a snapshot that another writer could have moved underneath the caller.

Casting a CAB vote is the first. A vote request must carry `expected_change_request_version` holding the `version` of the target `ChangeRequest` that the voter last observed. If that value does not equal the change's current `version` — for example because an earlier vote already advanced the tally, possibly to a quorum-reaching decision, since the voter last read the change — the vote is rejected with `ERR_STALE_VERSION` (HTTP 412), so a vote can never land on a tally the voter has not seen.

Routing a ticket is the second. A route request must carry `expected_ticket_version` holding the `version` of the target `Ticket` the agent last observed. If another agent has since routed, reprioritized, or otherwise advanced that ticket, its current `version` will differ and the route is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the queue depths and OLA leg from being re-derived off a superseded snapshot. No other endpoint accepts a version field; only voting and routing are OCC-guarded.

### 2.8. The SLA Clock and the Test-Driving Time Source

All SLA arithmetic is measured against a single server clock, expressed in whole minutes. The platform exposes an administrative capability to set that clock to an absolute instant and another to advance it by a number of minutes; these exist so evaluators can deterministically reach a due instant. Setting the clock to an absolute instant does not retroactively fire breaches — a breach is only recognized the next time the affected ticket transitions or the clock is advanced across the due instant. Advancing the clock, by contrast, actively evaluates every running ticket and fires the breach transitions for any whose due instant has just been crossed.

Time boundaries throughout the platform are **inclusive of the due instant**: a ticket whose work completes exactly at its due minute is on time, not late. All minute deltas are computed as whole minutes; partial minutes are floored when crediting paused time and rounded up when sizing a window from a multiplier (see §3).

### 2.9. Numeric Precision and Rounding

Money-style and score computations follow fixed precision rules and use round-half-up wherever rounding occurs. SLA windows are sized in whole minutes by rounding the multiplied base **up** to the next whole minute (ceiling) before any integer minutes are added. The group load score rounds each per-ticket term to two decimal places, sums those rounded terms, and rounds the grand total to one decimal place. The CSAT computation rounds the average score to two decimals, the response rate to four decimals, and the final index to two decimals. The precise order of these operations is part of each formula and is given in §3; the order is authoritative because rounding before versus after summation yields different results.

## 3. Business Logic & Workflows

### 3.1. Configuring the Service Catalog

Before any ticket can be opened, a `PlatformAdmin` lays down the configuration backbone. An SLA policy is registered with a display `name`, a `response_target_minutes` and a `resolve_target_minutes` (each expected to be a positive whole number of business minutes, with the resolve target normally no smaller than the response target — the server validates only that each is supplied as an integer and does not reject zero, negative, or out-of-order values), an `ola_target_minutes` for the internal hand-off leg, and a `priority_multipliers` map that scales all three targets per priority — for example a map that tightens P1 to a quarter of the base, P2 to half, leaves P3 at the base, and relaxes P4 to double. A category is then registered with a `name`, a `default_priority` (one of `P1`, `P2`, `P3`, `P4`), a `sla_policy_id` pointing at the governing policy, a `default_assignment_group_id` naming the queue its tickets land in, and an `active` flag that defaults to true and is recorded on the category to signal whether it should accept new tickets (the flag is stored and echoed back but is not currently enforced as a gate at open time — opening under an inactive category still succeeds). An assignment group is registered with a `name` and an `is_fulfilment_group` flag (default false) that marks internal fulfilment queues subject to OLA timing as opposed to the front-line service desk; its `queue_depth` starts at zero and is thereafter a computed count of the tickets sitting in it whose `lifecycle_state` is one of `NEW`, `ASSIGNED`, `IN_PROGRESS`, `PENDING_CHANGE`, or `ON_HOLD`. Assets are registered with a unique `asset_tag` and a `kind` of `SERVER`, `LAPTOP`, `NETWORK_DEVICE`, or `APPLICATION`; a duplicate `asset_tag` is rejected with `ERR_DUPLICATE_ASSET_TAG`. A new asset begins with `status` `OPERATIONAL` and an `open_incident_count` of zero. Knowledge-base articles are authored with a `title`, a `category_id` they are suggested under, and a `body`; each starts with a `view_count` and a `deflection_count` of zero.

### 3.2. Opening a Ticket and Deflection

A requester (or an agent acting on their behalf) opens a ticket by supplying a `short_description`, a `category_id`, and optionally an explicit `priority`, an `asset_id` for the affected configuration item, and a deflection pair of `kb_article_id` and `accept_deflection`. On a normal open, the ticket is created with `lifecycle_state` `NEW`; its `requester_id` is set from the caller's `X-User-ID`; its `assignment_group_id` is copied from the category's `default_assignment_group_id`; its effective `priority` is the supplied value or, when absent, the category's `default_priority`; its `opened_at` is stamped with the current clock; its `sla_state` is `RUNNING`; and the target group's `queue_depth` is recomputed upward. If an `asset_id` is supplied, the ticket is linked and that asset's `open_incident_count` is recomputed. At open time the platform computes the provisional SLA due dates: it looks up the multiplier for the ticket's priority in the policy's `priority_multipliers`, multiplies the policy's `response_target_minutes` by that multiplier and rounds the product up to a whole number of minutes, multiplies the policy's `resolve_target_minutes` by the same multiplier and rounds that product up as well, then sets `response_due_at` to `opened_at` plus the rounded response window and `resolve_due_at` to `opened_at` plus the rounded resolve window. At open the ticket's `paused_total_minutes` is zero, so no paused credit enters the resolve window yet.

Deflection short-circuits this flow. When the open call carries `accept_deflection` set to true together with a valid `kb_article_id`, the ticket is opened and then immediately auto-cancelled: its `lifecycle_state` becomes `CANCELLED`, its `deflected` flag is set to true, and the referenced article's `deflection_count` and `view_count` are each incremented. Both conditions must hold for deflection to trigger; `accept_deflection` true with no `kb_article_id` supplied simply opens an ordinary `NEW`, non-deflected ticket with no error. A `kb_article_id` that names no article is rejected with `ERR_FK_NOT_FOUND` whether or not deflection is accepted. This is the only path that sets `deflected`. The values `priority`, `risk`, vote `decision`, and CSAT `score` are validated against their allowed sets at creation: a `priority` outside `P1`–`P4`, a `risk` outside `LOW`/`MEDIUM`/`HIGH`, a `decision` outside `APPROVE`/`REJECT`, or a `score` outside the integer range 1 through 5 inclusive is rejected with `ERR_INVALID_FIELD_VALUE`. A create call missing a required field or sending it with the wrong type is rejected with `ERR_VALIDATION`.

### 3.3. Triage, Assignment, and Routing

Two early actions move a `NEW` ticket toward work. Assigning attaches an engineer by writing the supplied `assignee_user_id` onto the ticket and advancing `lifecycle_state` from `NEW` to `ASSIGNED`. Routing moves the ticket between queues: it writes the supplied `assignment_group_id`, recomputes both the source and the target group's `queue_depth`, and — when the destination's `is_fulfilment_group` is true — starts the OLA leg by setting the OLA hand-off timer from the policy's `ola_target_minutes`. Routing is the OCC-guarded operation described in §2.7: the request must carry `expected_ticket_version` equal to the ticket's current `version`, and a mismatch yields `ERR_STALE_VERSION`. Both assigning and routing require the ticket to be in `NEW`; either action attempted against a ticket not in `NEW` is rejected with `ERR_INVALID_STATE` (for routing this state check is evaluated before the OCC version check). Routing does not itself change `lifecycle_state` — the ticket remains `NEW` after a route — only assigning advances it to `ASSIGNED`.

Reprioritizing changes a ticket's `priority` after the fact. The new priority is written, and the SLA windows are recomputed under the **final** variant of the due-date calculation: both windows are re-derived from the new priority's multiplier but the window is still anchored on the **original** `opened_at` — the platform never re-anchors to "now" — and the recomputed `resolve_due_at` re-adds, after the ceiling, both the already-accumulated `paused_total_minutes` and the reopen penalty of sixty minutes per prior reopen (`reopen_count` × 60), exactly as the effective-resolve-window formula of §3.4 prescribes. Reprioritizing is not gated on lifecycle state; it is accepted from any state the ticket happens to be in. The `response_due_at` is recomputed only if no first response has yet been recorded; once first response has happened, the response window is settled and left untouched.

### 3.4. Working the Ticket: First Response, Holds, and the Paused Clock

When an agent starts work, the ticket advances from `ASSIGNED` to `IN_PROGRESS` and the platform records first response by clearing `response_due_at` to null. At that same moment it evaluates the response leg of the SLA: if the current clock is at or before the recorded `response_due_at`, the response target is met and the `sla_state` is left as it was (a still-running ticket stays `RUNNING`; there is no distinct "response-met" value); if the current clock is strictly past it, the ticket's `sla_state` becomes `RESPONSE_BREACHED`. Starting work against a ticket not in `ASSIGNED`, or one whose `assignee_user_id` is still null, is rejected with `ERR_INVALID_STATE`.

An in-progress ticket can be paused two ways, and both freeze the SLA clock identically. Placing a ticket on hold moves `lifecycle_state` from `IN_PROGRESS` to `ON_HOLD`; attaching a change (covered in §3.5) moves it to `PENDING_CHANGE`. In either case the `sla_state` becomes `PAUSED` and the platform records the instant the pause began, `pause_started_at`, on the ticket's SLA timer. Pausing does not itself alter `resolve_due_at`; the credit is applied when the pause ends, not when it begins. Resuming a held ticket moves it from `ON_HOLD` back to `IN_PROGRESS`: the platform measures the elapsed paused interval as the whole number of minutes between `pause_started_at` and the current clock, adds that delta to the ticket's `paused_total_minutes`, pushes `resolve_due_at` out by the same delta, and sets `sla_state` back to `RUNNING`. The response window is never extended on resume, because the response leg is already settled — met or breached — before any pause is possible.

The effective resolve window can therefore be reconstructed at any time from three interacting inputs. Start from the policy's `resolve_target_minutes`, multiply by the ticket's priority multiplier, and round that product up to a whole minute. To that ceiling, add the ticket's accumulated `paused_total_minutes`, and then add the reopen penalty, which is sixty minutes for each time the ticket has been reopened. The two additions happen after the ceiling, never before it, and `resolve_due_at` is `opened_at` plus this effective figure. The ordering is pinned: the multiplied base is ceiled first, then the integer minutes are added.

### 3.5. Change Control: Raising, Submitting, and Voting

When resolving a ticket requires a controlled change, an agent attaches a change to it. A `ChangeManager` first raises the change with a `title`, the `ticket_id` it implements, and a `risk` of `LOW`, `MEDIUM`, or `HIGH`; the change starts in `state` `DRAFT` and records the manager's `X-User-ID` as `raised_by_user_id`. Submitting the change advances it from `DRAFT` to `PENDING_CAB` and derives the `required_approvals` quorum from its risk — one approval for `LOW`, two for `MEDIUM`, three for `HIGH` — while resetting `approve_count` and `reject_count` to zero. Only the manager who raised the change may submit it.

Attaching the change to a ticket is an agent action available only while the ticket is `IN_PROGRESS` and only when the referenced change exists, belongs to that ticket, and is itself in `DRAFT` or `PENDING_CAB`. A `change_request_id` that names no change is rejected with `ERR_FK_NOT_FOUND`; a ticket not in `IN_PROGRESS` with `ERR_INVALID_STATE`; and a referenced change that exists but does not belong to this ticket or is not in `DRAFT`/`PENDING_CAB` likewise with `ERR_INVALID_STATE`. The attach writes the change's id into the ticket's `change_request_id`, moves `lifecycle_state` to `PENDING_CHANGE`, sets `sla_state` to `PAUSED`, and records `pause_started_at` — the SLA clock pauses exactly as it does for a hold.

`CabMember`s then vote. Each vote names the `change_request_id`, carries a `decision` of `APPROVE` or `REJECT`, and carries `expected_change_request_version` for the OCC check of §2.7. A vote against a change not currently in `PENDING_CAB` is rejected with `ERR_INVALID_STATE`, evaluated before the OCC version check. Two safety rules guard the vote and are evaluated as part of casting it: the change's own `raised_by_user_id` may never vote on that change — an attempt is rejected with `ERR_SOD_VIOLATION` — and a given `voter_user_id` may vote at most once per change, with a second attempt rejected with `ERR_DUPLICATE_VOTE`. Each accepted vote is appended as an immutable record and the change's tally is recomputed from the distinct votes on it: `approve_count` is the number of distinct voters who chose `APPROVE` and `reject_count` the number who chose `REJECT`. The tally then decides the change's fate with a pinned evaluation order. On an approve vote, approve quorum is checked first: if `approve_count` has reached `required_approvals`, the change moves from `PENDING_CAB` to `APPROVED`. On a reject vote, the veto is checked: a single reject is enough — the veto threshold is one — so any reject moves the change from `PENDING_CAB` to `REJECTED`. The veto dominates once a reject is present; an approve vote is only ever evaluated for quorum, and a reject vote is only ever evaluated for veto. If neither threshold is met, the change stays `PENDING_CAB`.

Whenever a vote drives the change to either `APPROVED` or `REJECTED`, a cascade bubbles up to the gated ticket: the linked ticket (named by the change's `ticket_id`) moves from `PENDING_CHANGE` back to `IN_PROGRESS`, its SLA resumes — the paused interval since `pause_started_at` is measured in whole minutes, added to `paused_total_minutes`, and added to `resolve_due_at`, with `sla_state` returning to `RUNNING` — and the ticket's `change_request_id` is cleared to null. The vote increments the change's `version`, and the resumed ticket's `version` and `updated_at` are refreshed too.

After approval, a `ChangeManager` may mark the change implemented, advancing it from `APPROVED` to `IMPLEMENTED`; this has no further effect on the ticket, which already resumed at approval. Alternatively the manager may mark an approved change failed, advancing it from `APPROVED` to `FAILED`. A change can only be implemented or failed from the `APPROVED` state; any other starting state yields `ERR_INVALID_STATE`.

### 3.6. Resolving, Reopening, Closing, and Cancelling

Resolving a ticket is an agent action available from `IN_PROGRESS`, accepting an optional `resolution_note` describing how the incident was closed out. The platform refuses to resolve while a non-terminal change still gates the ticket — that is, while `change_request_id` is not null — rejecting the attempt with `ERR_CHANGE_GATING_RESOLUTION`. On a clean resolve, `lifecycle_state` moves to `RESOLVED`, `resolved_at` is stamped with the current clock, and the resolve leg of the SLA is evaluated: if the current clock is at or before `resolve_due_at` the `sla_state` becomes `MET`, and if it is strictly past it the `sla_state` becomes `RESOLVE_BREACHED`. The owning group's `queue_depth` is recomputed downward, and if the ticket carries a `problem_id`, that problem's `linked_ticket_count` is recomputed.

A resolved ticket can be reopened by its own requester within a fixed window. Reopening is permitted only while the current clock is at or before `resolved_at` plus the reopen window of twenty-four hours (1440 minutes), and only when the caller's `X-User-ID` matches the ticket's `requester_id`; an attempt past the window is rejected with `ERR_REOPEN_WINDOW_CLOSED`, one against a ticket not in `RESOLVED` with `ERR_INVALID_STATE`, and a caller whose `X-User-ID` does not match the ticket's `requester_id` with `ERR_FORBIDDEN` — checked in that order, so the state check fires first, then the reopen-window check, then the ownership check. A successful reopen moves `lifecycle_state` from `RESOLVED` back to `IN_PROGRESS`, increments `reopen_count` by one, sets `sla_state` to `RUNNING`, recomputes the owning group's `queue_depth` upward, and applies the reopen penalty: `resolve_due_at` is pushed out by sixty minutes for this reopen event, so that after N reopens the cumulative penalty embedded in the window is sixty minutes times `reopen_count`.

Closing a resolved ticket moves `lifecycle_state` from `RESOLVED` to `CLOSED`. Closing is allowed once the reopen window has elapsed — the current clock is strictly past `resolved_at` plus the twenty-four-hour reopen window — or, earlier than that, once a satisfaction survey already exists for the ticket; an attempt that satisfies neither condition is rejected with `ERR_INVALID_STATE`. If the ticket carries an `asset_id`, closing recomputes that asset's `open_incident_count`. A `NEW` ticket that the requester no longer needs can instead be cancelled by its own requester — `X-User-ID` matching `requester_id`, a mismatch being rejected with `ERR_FORBIDDEN` evaluated after the `NEW`-state check — moving `lifecycle_state` from `NEW` to `CANCELLED` and recomputing the owning group's `queue_depth` downward.

### 3.7. Satisfaction Measurement

Once a ticket is resolved, its requester may file exactly one satisfaction survey, supplying the `ticket_id`, an integer `score` from 1 to 5 inclusive, and an optional free-text `comment`. A second survey for the same ticket is rejected with `ERR_DUPLICATE_SURVEY`. The survey records whether it `counts_toward_index`: this is true only when the survey is filed within the CSAT eligibility window of forty-eight hours (2880 minutes) after the ticket's `resolved_at`. A survey submitted past that hard window is rejected outright with `ERR_CSAT_WINDOW_CLOSED`; a survey filed against a ticket that has never been resolved (no `resolved_at`) is likewise rejected with `ERR_CSAT_WINDOW_CLOSED` since its window has not opened; a survey within the window is stored with `counts_toward_index` set to true.

The per-group CSAT index is a derived read evaluated in a pinned four-step order. First, determine the eligible surveys: those whose `counts_toward_index` is true — that is, filed within the 2880-minute window of their ticket's `resolved_at` — for tickets whose `assignment_group_id` is this group. Second, compute `avg_score` as the sum of the eligible surveys' scores divided by their count, rounded half-up to two decimals. Third, compute `response_rate` as the count of eligible surveys divided by the count of resolved-or-closed tickets in the group resolved within the window, rounded half-up to four decimals. Fourth, compute `csat_index` as `avg_score` times twenty times `response_rate`, rounded half-up to two decimals, yielding a figure on a zero-to-one-hundred scale. If the third step's denominator is zero, the `csat_index` is exactly 0.0 and the reported `response_rate` is 0.0, while `avg_score` is still computed from whatever eligible surveys exist (or 0.0 when there are none). The computed read reports `csat_index`, `avg_score`, `response_rate`, and the `eligible_count` of surveys that counted.

### 3.8. Problems, Known Errors, and Asset Health

An agent opens a problem to investigate a recurring root cause, supplying a `title`, the `owner_user_id`, and optionally an `asset_id` for the suspected failing component; the problem starts in `state` `OPEN` with a `linked_ticket_count` of zero. Tickets are attached to a problem as symptoms via the link action, which writes the ticket's `problem_id` and recomputes the problem's `linked_ticket_count`, counting only those linked tickets whose `lifecycle_state` is not `CLOSED` or `CANCELLED`.

The investigation advances through its own lifecycle. Identifying the root cause moves the problem from `OPEN` to `ROOT_CAUSE_IDENTIFIED`; if the call supplies an `asset_id`, that asset is recorded on the problem and its `status` cascades from `OPERATIONAL` to `DEGRADED`. Promoting to a known error creates a `KnownError` record — carrying the `problem_id`, a `symptom`, and a `workaround`, with `published` set to true so it can feed deflection — and moves the problem from `ROOT_CAUSE_IDENTIFIED` to `KNOWN_ERROR`. Finally, resolving a problem moves it from `KNOWN_ERROR` to `RESOLVED`, but only once its `linked_ticket_count` has fallen to zero; an attempt while symptom tickets remain open is rejected with `ERR_PROBLEM_HAS_OPEN_TICKETS`, and one from the wrong state with `ERR_INVALID_STATE`. When a problem with a recorded asset resolves and no other open problem still references that asset, the asset's `status` cascades from `DEGRADED` back to `OPERATIONAL`.

Assets carry their own health lifecycle. An asset's `open_incident_count` is the count of tickets linked to it via `asset_id` whose `lifecycle_state` is not `RESOLVED`, `CLOSED`, or `CANCELLED`. An asset may be retired by a `PlatformAdmin` only from `OPERATIONAL` and only when its `open_incident_count` is zero; a retire attempted while incidents remain open is rejected with `ERR_ASSET_HAS_OPEN_INCIDENTS`, moving `status` to the terminal `RETIRED` only when the count is clear.

### 3.9. Queue Load and the Test Clock

Operators monitoring a queue can read its weighted load score, a derived figure computed over the group's non-terminal tickets — those whose `lifecycle_state` is one of `NEW`, `ASSIGNED`, `IN_PROGRESS`, `PENDING_CHANGE`, or `ON_HOLD`. For each such ticket, take its priority weight — eight for `P1`, four for `P2`, two for `P3`, one for `P4` — multiply by a breach factor of one-and-a-half when the ticket's `sla_state` is `RESPONSE_BREACHED` or `RESOLVE_BREACHED` and one otherwise, divide by three, and round that per-ticket term half-up to two decimals. Sum the rounded per-ticket terms, then round the grand total half-up to one decimal place to produce the `load_score`. The per-line rounding before summation is authoritative: summing the raw terms and rounding once would yield a different figure. The read reports the `load_score` alongside the `ticket_count` of non-terminal tickets considered.

The platform's logical clock is driven by two administrative capabilities used to exercise time-dependent behavior deterministically. One capability sets the clock to an absolute instant supplied as `to_iso8601` and reports the resulting `now`; setting the clock does not retroactively fire breaches. The other advances the clock by a supplied number of `minutes`, reports the new `now`, and actively evaluates breaches: for every running ticket whose `response_due_at` is crossed while still awaiting first response, `sla_state` becomes `RESPONSE_BREACHED`; for every running ticket whose `resolve_due_at` is crossed while still unresolved, `sla_state` becomes `RESOLVE_BREACHED`. The advance reports the list of `breached_ticket_ids` it transitioned.

### 3.10. Validation Ordering

When several checks could fire on one request, they are evaluated in a fixed priority order so the most fundamental failure is the one reported. Authentication comes first: a missing `X-User-ID` or `X-User-Role` yields `ERR_UNAUTHENTICATED`. Authorization is next: a role not permitted for the operation yields `ERR_FORBIDDEN`. Then path existence is checked left to right, yielding `ERR_NOT_FOUND` for a missing path target, followed by body foreign-key existence, yielding `ERR_FK_NOT_FOUND`. Lifecycle-state legality is checked next, yielding `ERR_INVALID_STATE`, and then — on the two OCC-guarded writes — the version check, yielding `ERR_STALE_VERSION`. Business-safety rules follow in order: the segregation-of-duties check (`ERR_SOD_VIOLATION`) precedes the duplicate-vote check (`ERR_DUPLICATE_VOTE`). Referential business rules come next — change-gated resolution (`ERR_CHANGE_GATING_RESOLUTION`), then a problem with open tickets (`ERR_PROBLEM_HAS_OPEN_TICKETS`), then an asset with open incidents (`ERR_ASSET_HAS_OPEN_INCIDENTS`). Temporal rules follow — the reopen window (`ERR_REOPEN_WINDOW_CLOSED`), then the CSAT window (`ERR_CSAT_WINDOW_CLOSED`). Finally come the constraint checks — duplicate survey (`ERR_DUPLICATE_SURVEY`), duplicate asset tag (`ERR_DUPLICATE_ASSET_TAG`), enum and range validity (`ERR_INVALID_FIELD_VALUE`), and missing-or-malformed body fields (`ERR_VALIDATION`).

## 4. Endpoint Definitions

Creation endpoints return HTTP 201 with the newly created resource; state transitions and other modifications return HTTP 200 with the updated resource. Reads return HTTP 200. The request body, response body, and side effects of each endpoint are described in the §3 narratives above and are not repeated here.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/categories` | Create a ticket category | PlatformAdmin |
| GET | `/categories/{id}` | Get a category | PlatformAdmin, Agent, ChangeManager, CabMember, Requester |
| GET | `/categories` | List categories | PlatformAdmin, Agent, ChangeManager, CabMember, Requester |
| POST | `/sla-policies` | Create an SLA/OLA policy | PlatformAdmin |
| GET | `/sla-policies/{id}` | Get an SLA policy | PlatformAdmin, Agent, ChangeManager, CabMember, Requester |
| POST | `/assignment-groups` | Create an assignment group / queue | PlatformAdmin |
| GET | `/assignment-groups/{id}` | Get an assignment group | PlatformAdmin, Agent, ChangeManager, CabMember, Requester |
| GET | `/assignment-groups/{id}/load` | Computed weighted group load score | PlatformAdmin, Agent |
| GET | `/assignment-groups/{id}/csat` | Computed group CSAT index | PlatformAdmin, Agent |
| POST | `/tickets` | Open a ticket (deflection-aware) | Requester, Agent |
| GET | `/tickets/{id}` | Get a ticket | PlatformAdmin, Agent, ChangeManager, CabMember, Requester |
| GET | `/tickets` | List tickets | PlatformAdmin, Agent, ChangeManager, CabMember, Requester |
| POST | `/tickets/{id}/route` | Route ticket to an assignment group (OCC-guarded) | Agent |
| POST | `/tickets/{id}/assign` | Assign an agent to the ticket | Agent |
| POST | `/tickets/{id}/start` | Begin work; record first response | Agent |
| POST | `/tickets/{id}/reprioritize` | Change ticket priority; recompute SLA windows | Agent |
| POST | `/tickets/{id}/hold` | Put ticket on hold (pause SLA) | Agent |
| POST | `/tickets/{id}/resume` | Resume a held ticket | Agent |
| POST | `/tickets/{id}/attach-change` | Attach a gating change; pause SLA | Agent |
| POST | `/tickets/{id}/link-problem` | Link ticket to a problem as a symptom | Agent |
| POST | `/tickets/{id}/resolve` | Resolve ticket; evaluate resolve SLA | Agent |
| POST | `/tickets/{id}/reopen` | Requester reopens within window | Requester |
| POST | `/tickets/{id}/close` | Close a resolved ticket | Agent |
| POST | `/tickets/{id}/cancel` | Requester cancels a NEW ticket | Requester |
| POST | `/problems` | Open a problem investigation | Agent |
| GET | `/problems/{id}` | Get a problem | PlatformAdmin, Agent, ChangeManager, CabMember, Requester |
| GET | `/problems` | List problems | PlatformAdmin, Agent, ChangeManager, CabMember, Requester |
| POST | `/problems/{id}/identify-root-cause` | Advance to ROOT_CAUSE_IDENTIFIED; optionally flag asset | Agent |
| POST | `/problems/{id}/known-errors` | Create a known-error record; promote problem | Agent |
| GET | `/problems/{id}/known-errors` | List known-error records for a problem | PlatformAdmin, Agent, ChangeManager, CabMember, Requester |
| POST | `/problems/{id}/resolve` | Resolve a problem (no open tickets) | Agent |
| GET | `/known-errors/{id}` | Get a known-error record | PlatformAdmin, Agent, ChangeManager, CabMember, Requester |
| POST | `/kb-articles` | Create a knowledge-base article | PlatformAdmin, Agent |
| GET | `/kb-articles/{id}` | Get a KB article | PlatformAdmin, Agent, ChangeManager, CabMember, Requester |
| GET | `/kb-articles` | List/search KB articles | PlatformAdmin, Agent, ChangeManager, CabMember, Requester |
| POST | `/change-requests` | Raise a change request (DRAFT) | ChangeManager |
| GET | `/change-requests/{id}` | Get a change request | PlatformAdmin, Agent, ChangeManager, CabMember, Requester |
| GET | `/change-requests` | List change requests | PlatformAdmin, Agent, ChangeManager, CabMember, Requester |
| POST | `/change-requests/{id}/submit` | Submit change to CAB; derive quorum | ChangeManager |
| POST | `/change-requests/{id}/votes` | Cast a CAB vote (OCC-guarded; SoD enforced) | CabMember |
| GET | `/change-requests/{id}/votes` | List votes for a change request | PlatformAdmin, Agent, ChangeManager, CabMember, Requester |
| POST | `/change-requests/{id}/implement` | Mark an approved change implemented | ChangeManager |
| POST | `/change-requests/{id}/fail` | Mark an approved change failed | ChangeManager |
| POST | `/csat-surveys` | Submit a CSAT survey (window-gated) | Requester |
| GET | `/csat-surveys/{id}` | Get a CSAT survey | PlatformAdmin, Agent, Requester |
| GET | `/csat-surveys` | List CSAT surveys | PlatformAdmin, Agent, Requester |
| POST | `/assets` | Register a configuration item / asset | PlatformAdmin |
| GET | `/assets/{id}` | Get an asset | PlatformAdmin, Agent, ChangeManager, CabMember, Requester |
| GET | `/assets/{id}/tickets` | List tickets linked to an asset | PlatformAdmin, Agent, ChangeManager, CabMember, Requester |
| POST | `/assets/{id}/retire` | Retire an asset with no open incidents | PlatformAdmin |
| POST | `/_clock/set` | Test-driving: set the server clock | PlatformAdmin |
| POST | `/_clock/advance` | Test-driving: advance the clock; fire breaches | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_VALIDATION | 400 |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_SOD_VIOLATION | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_FK_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_CHANGE_GATING_RESOLUTION | 409 |
| ERR_PROBLEM_HAS_OPEN_TICKETS | 409 |
| ERR_ASSET_HAS_OPEN_INCIDENTS | 409 |
| ERR_REOPEN_WINDOW_CLOSED | 409 |
| ERR_CSAT_WINDOW_CLOSED | 409 |
| ERR_DUPLICATE_SURVEY | 409 |
| ERR_DUPLICATE_VOTE | 409 |
| ERR_DUPLICATE_ASSET_TAG | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_FIELD_VALUE | 422 |
