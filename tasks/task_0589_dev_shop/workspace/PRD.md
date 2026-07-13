# Dev Shop Delivery API — Product Requirements Document

## 1. Introduction

A software development shop lives and dies by the gap between what it estimated and what it actually spent. A lead arrives through a referral, an account manager qualifies it, a statement of work pins a contract value and an hour cap, and from that moment every hour an engineer logs is a withdrawal from a budget that nobody watches closely enough until it is already overdrawn. Meanwhile the client asks for "one small extra feature", the change request is quoted, negotiated, re-quoted, and approved — silently enlarging the very budget the burn was being measured against. Finished work goes to staging, gets QA'd, gets rejected, gets reworked, is finally accepted, and only then does anyone remember to raise the milestone invoice. After delivery, a maintenance retainer takes over, support incidents arrive with severity labels, and service-level breaches turn into credits that must be netted off the next retainer invoice.

This document specifies the Dev Shop Delivery API: a single backend that carries an engagement from first contact through signed SOW, sprint execution, time approval, scope negotiation, release acceptance, milestone billing, and post-launch support under an SLA. Two ledgers sit at the centre of the design — an **hours ledger** (approved billable time rolled up from tickets to the engagement) and a **money ledger** (invoiced currency rolled up from invoices to the engagement) — and both are strictly conserved: every approval has an exact reversal, every issue has an exact void, and no operation may leave either ledger drifted by so much as a cent or a hundredth of an hour.

The system is deliberately opinionated about *when* a team is allowed to keep spending. Burn is recomputed on every hours movement, a posture is derived from it, and that posture reaches down into the active sprints and freezes them. Engineers discover the freeze not through a dashboard but by being unable to start a ticket. That is the intended behaviour, and it is the reason most of the rules below exist.

## 2. Global Specifications & System-Wide Principles

### 2.1. Actors, Identity and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role that user is acting under. If either header is absent, or if `X-User-Role` is not one of the six roles the platform recognises, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the named role is not among the roles authorised for the endpoint being called (see the authorisation column of the endpoint table in §4), the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The six roles are `AccountManager`, `DeliveryLead`, `Engineer`, `ClientContact`, `FinanceOfficer`, and `PlatformAdmin`. An `AccountManager` owns the commercial funnel: registering client companies, opening leads, qualifying them, issuing statements of work, and opening maintenance retainers. A `DeliveryLead` is the project manager: milestones, sprints, tickets, blocker management, time review and reversal, change-request authoring, and engagement closure. An `Engineer` builds: works tickets, logs time, cuts releases, records staging QA results, deploys, and handles support incidents. A `ClientContact` is the client side of the table: signing the SOW, deciding change requests, accepting or rejecting releases, and raising support incidents. A `FinanceOfficer` handles all four invoice operations — create, issue, pay, void. A `PlatformAdmin` is an operator who may reposition the server's logical clock and may also register client companies. Every role may call every read endpoint.

Identity semantics differ by role, and this distinction matters for ownership checks. When `X-User-Role` is `ClientContact`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` compare the resource's client foreign key — directly on a retainer, or transitively through the engagement for an engagement, release, change request, invoice, or support incident — to `X-User-ID`. When `X-User-Role` is `AccountManager`, `DeliveryLead`, `Engineer`, `FinanceOfficer`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow demands it — as `employee_user_id` on a time entry, as `reviewed_by_user_id` on a reviewed time entry, and as the `assignee_user_id` that a delivery lead nominates when creating a ticket — but it never compares those opaque identifiers to any entity's `id`.

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

Every list endpoint accepts two optional query parameters, `limit` and `offset`. `limit` defaults to 10 when omitted, must be at least 1, and must not exceed 100. `offset` defaults to 0 when omitted and must be at least 0. A `limit` outside the range 1 through 100 inclusive, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Lists are returned sorted by `created_at` in ascending order — oldest first — regardless of any filter applied. The `meta` block of a list response carries `limit`, `offset`, `total_count` (the number of records matching the filters before pagination is applied) and `has_more` (true when records remain beyond the current page). All filter parameters on list endpoints are optional; when several are supplied they are combined conjunctively.

### 2.4. Common Resource Properties, Versioning and the Logical Clock

Every resource in this system carries an `id` (a server-minted UUID with no type prefix), a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`. Timestamps are ISO 8601 UTC with three fractional digits. `version` is 1 at creation and increments by 1 on every mutation of that resource; `updated_at` is refreshed to the current logical clock on every mutation. Every entity in this system — clients, engagements, milestones, sprints, tickets, time entries, change requests, releases, invoices, retainer contracts and support incidents — carries the full set.

Time in this system is *logical*, not wall-clock. The server holds a logical clock whose startup default is exactly `2026-05-01T00:00:00Z`; before any reposition it reads that default and never falls back to real wall-clock time. A `PlatformAdmin` may reposition the clock to a supplied `to_iso8601` instant, and the response echoes back the new `current_utc`. Repositioning the clock mutates no entity. Every timestamped business moment — `signed_at` on an engagement, `accepted_at` on a milestone and on a release, `issued_at` and `paid_at` on an invoice, and `opened_at`, `responded_at` and `resolved_at` on a support incident — is stamped from this clock and from nothing else.

### 2.5. Flat Addressing, Reference Resolution, and the Order in Which Requests Are Judged

Resources are addressed flatly: each entity type lives at its own top-level collection and links to its peers through foreign-key fields carried in the request body rather than through nested URL segments. A path identifier that does not resolve to an existing resource produces the corresponding not-found error for that entity type — `ERR_CLIENT_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`, `ERR_SPRINT_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_TIME_ENTRY_NOT_FOUND`, `ERR_CHANGE_REQUEST_NOT_FOUND`, `ERR_RELEASE_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_RETAINER_NOT_FOUND` or `ERR_INCIDENT_NOT_FOUND` — all at HTTP 404. Where an endpoint carries more than one identifier, they are validated left to right, so the leftmost unresolvable identifier is the one reported. The same not-found treatment applies to every foreign key supplied in a creation body — `client_id`, `engagement_id`, `milestone_id`, `sprint_id`, `ticket_id`, `retainer_id` and `blocking_ticket_id` — on every creation endpoint in the system.

Because a single request can violate several rules at once, the order in which checks are applied is fixed, and the first failing check is the one reported. The precedence chain, from highest to lowest, is:

1. **Authentication** — headers present and the role recognised (`ERR_UNAUTHENTICATED`).
2. **Role authorisation** — the acting role is listed for the endpoint (`ERR_FORBIDDEN_ROLE`).
3. **Path-identifier existence** — left-to-right, each identifier in the URL resolves (the entity-specific not-found error).
4. **Body foreign-key existence** — every foreign key in the payload resolves (the entity-specific not-found error).
5. **Body well-formedness** — required fields present, enum values recognised, numbers positive where a positive number is required, dates in `YYYY-MM-DD` form, logged hours greater than 0 and no greater than 12, `limit` within 1 through 100, `offset` at least 0 (`ERR_INVALID_REQUEST`).
6. **Client scope confinement** — see §2.6 (`ERR_CLIENT_SCOPE_VIOLATION`).
7. **Optimistic concurrency** — see §2.7 (`ERR_STALE_ENGAGEMENT_VERSION`).
8. **Parent-state gates** — the engagement must be `ACTIVE` where the operation demands it (`ERR_ENGAGEMENT_NOT_ACTIVE`), then the sprint-state gates (`ERR_SPRINT_NOT_ACTIVE`), then the transition-legality check (`ERR_INVALID_TRANSITION`), then the milestone-completion gate on issuing (`ERR_MILESTONE_NOT_COMPLETED`), then the active-sprint gate on engagement closure (`ERR_ENGAGEMENT_HAS_ACTIVE_SPRINT`).
9. **Segregation of duties** (`ERR_SEGREGATION_OF_DUTIES`).
10. **Referential business rules** — ticket assignee ownership (`ERR_NOT_TICKET_ASSIGNEE`), then blocker-graph acyclicity (`ERR_TICKET_CYCLE`), then milestone-to-engagement consistency (`ERR_MILESTONE_ENGAGEMENT_MISMATCH`).
11. **Temporal rules** — work-date containment (`ERR_WORK_DATE_OUT_OF_SPRINT`), then sprint-window overlap (`ERR_SPRINT_OVERLAP`), then retainer-window collision (`ERR_RETAINER_WINDOW_CONFLICT`), then retainer-coverage activity (`ERR_RETAINER_WINDOW_INACTIVE`).
12. **Spend and flow constraints** — spend freeze (`ERR_SPRINT_SPEND_FROZEN`), then blocker readiness (`ERR_TICKET_BLOCKED`), then the change-request revision limit (`ERR_CR_ROUND_LIMIT`), then invoice-kind compatibility (`ERR_INVOICE_KIND_MISMATCH`), then the empty-lines gate (`ERR_INVOICE_NO_LINES`), then the duplicate-milestone-invoice gate (`ERR_DUPLICATE_MILESTONE_INVOICE`).
13. **Fiscal caps** — the budget hour cap (`ERR_BUDGET_HOURS_EXCEEDED`), the daily hour cap (`ERR_DAILY_HOURS_EXCEEDED`), the milestone-sum cap (`ERR_MILESTONE_AMOUNT_EXCEEDS_CONTRACT`), and the exact-payment rule (`ERR_PAYMENT_AMOUNT_MISMATCH`).

Two consequences are worth spelling out. A stale-version rejection outranks every business-state check, so a change-request creation carrying an out-of-date engagement version is reported as a stale-version failure even if the engagement is also not active. And segregation of duties outranks all the referential and fiscal rules, so a delivery lead who tries to approve their own time entry hears about the conflict of interest rather than about the budget.

### 2.6. Client Scope Confinement

The `ClientContact` role is confined to its own client's data. On every endpoint that touches an `Engagement`, a `Release`, a `ChangeRequest`, a `RetainerContract` or a `SupportIncident` — reads and writes alike — the client to which the target resource ultimately belongs must be the same client whose `id` is presented in `X-User-ID`. A retainer belongs to the client named by its `client_id`; an engagement belongs to the client named by its `client_id`; a release, change request, invoice or support incident belongs to whichever client owns the engagement or retainer it hangs from. When a `ClientContact` reaches for a resource belonging to a different client, the request is rejected with `ERR_CLIENT_SCOPE_VIOLATION` (HTTP 403). The five operator roles are not scope-confined.

### 2.7. Optimistic Concurrency on the Engagement Ledger

Two write paths take an optimistic-concurrency guard against the parent engagement, because both of them make a decision on the basis of a ledger snapshot that they must not be allowed to overwrite blindly.

Opening a change request requires `expected_engagement_version` in the body, carrying the `version` of the target `Engagement` as the client last observed it. If that number does not equal the engagement's current `version` — because some other writer has advanced the engagement since the read — the create is rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412). A change request legitimately supersedes the engagement's scope assumptions (its approval mutates `contract_value` and `budget_hours_cap`), so without this pin a second create against the same observed version would be accepted under the natural product semantics and the two authors would each believe they were negotiating against the same baseline.

Creating an invoice likewise requires `expected_engagement_version` in the body, carrying the `version` of the target `Engagement` as the finance officer last observed it. Invoice creation snapshots the engagement's billing ledger — approved hours, milestone status, contract value — so if the engagement's `version` has advanced since that read, the snapshot is stale and the create is rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412).

No other endpoint in the system takes a version field. Sprints, tickets, time entries, releases, retainers and support incidents are created and driven without any version pin.

### 2.8. Money, Hours and Rounding Discipline

All currency amounts carry 2 decimal places and every currency rounding in this system is **round half up**. Hours likewise carry 2 decimal places. Ratios — the engagement's `burn_ratio` and a ticket's `variance_ratio` — carry 4 decimal places, also rounded half up. SLA durations are whole minutes, always rounded **down** (floored).

Where a total is composed of parts, *the point at which rounding happens is part of the specification and is not negotiable*. The engagement's burn rounds **once, on the aggregate**: total approved hours are multiplied by the blended rate and the single product is rounded. An invoice rounds **per line and then sums**: each line amount is rounded to 2 decimal places on its own, and the subtotal is the plain arithmetic sum of those already-rounded line amounts with no further rounding applied. For identical hours these two disciplines can disagree by a cent. That divergence is intentional; each figure is correct under its own pinned rule, and neither may be "reconciled" against the other.

### 2.9. The Two Conserved Ledgers

The engagement maintains two rollups that must at all times equal the aggregate of their sources, exactly, with zero drift permitted.

The **hours ledger**: an engagement's `approved_hours` must equal the sum of `hours` over every time entry that is `APPROVED`, is marked billable, and whose ticket rolls up through a sprint to that engagement. A ticket's `actual_hours` must equal the sum of `hours` over every `APPROVED` time entry against that ticket. Approving an entry and then reversing it must leave both sums — and therefore `burned_cost`, `burn_ratio`, `budget_posture`, and every affected sprint's `spend_frozen` flag — at exactly the values they held before the approval.

The **money ledger**: an engagement's `invoiced_amount` must equal the sum of `subtotal` over every invoice of that engagement whose status is `ISSUED` or `PAID`. Invoices in `DRAFT` or `VOID` contribute nothing. Issuing an invoice and then voiding it must restore `invoiced_amount`, the engagement's `billing_status`, and the linked milestone's own status to exactly their pre-issue values. Note that `invoiced_amount` is a sum of subtotals — it is tax-exclusive.

`billing_status` is a pure function of that money ledger, recomputed after every issue and every void, and it moves independently of the engagement's delivery `status`: an `ACTIVE` engagement may be `UNBILLED`, `PARTIALLY_BILLED` or `FULLY_BILLED`. When `invoiced_amount` is exactly 0 the engagement is `UNBILLED`. When `invoiced_amount` is greater than or equal to `contract_value` it is `FULLY_BILLED`. In every other case — a positive `invoiced_amount` strictly below `contract_value` — it is `PARTIALLY_BILLED`. Every recomputation of `billing_status` on issue or void increments the engagement's `version` by 1.

### 2.10. Segregation of Duties

Two operations in this system are self-approval risks, and both are blocked. A delivery lead may not review a time entry whose `employee_user_id` equals their own `X-User-ID`. And the actor who signs a ticket off — moving it from `IN_QA` to `DONE` — may not be the ticket's `assignee_user_id`. Both comparisons are made against the opaque `X-User-ID` header, and both rejections carry `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). Note the asymmetry: an engineer *may* freely move their own ticket through `TODO`, `IN_PROGRESS`, `IN_QA` and `REWORK`; it is only the final sign-off that requires a second pair of eyes.

## 3. Business Logic & Workflows

### 3.1. From Lead to Signed Statement of Work

Everything begins with a client company. An account manager registers one by supplying its `name`, the `billing_email` where invoices will be sent, and a `country_code` given as exactly two uppercase letters. A platform administrator may register clients too, but no one else may.

With a client on file, the account manager opens an engagement by naming the `client_id` it belongs to, a `title`, and a `source_channel` recording how the lead arrived — one of `REFERRAL`, `INBOUND`, `OUTBOUND` or `PARTNER`. The new engagement is born in `LEAD` status, `UNBILLED` on its billing dimension, `HEALTHY` on its budget dimension, and at `version` 1. Its commercial terms — `billing_model`, `contract_value`, `budget_hours_cap`, `standard_hourly_rate`, `start_date` and `end_date` — are all null at this point; the lead has not been priced.

Qualification is the account manager's judgement call. The decision carries an `outcome` and an optional `note`; an outcome of `QUALIFY` advances a `LEAD` to `QUALIFIED`, while an outcome of `DISQUALIFY` moves it to `DISQUALIFIED`. Both refresh `updated_at` and bump the engagement's `version` by 1. `DISQUALIFIED` is terminal: no statement of work may ever be issued against a disqualified lead, and any attempt to advance it further draws `ERR_INVALID_TRANSITION` (HTTP 409). Qualification is only available from `LEAD`; qualifying an already-qualified engagement draws the same error.

Issuing the statement of work is the moment the engagement acquires economics. Only a `QUALIFIED` engagement may receive one. The account manager supplies the `billing_model` — either `FIXED` or `TIME_AND_MATERIALS` — together with `contract_value`, `budget_hours_cap`, `standard_hourly_rate`, `start_date` and `end_date`. All three numbers must be strictly greater than zero, `contract_value` and `standard_hourly_rate` at 2 decimal places, and `start_date` must be no later than `end_date`; a violation of any of these is a malformed body and draws `ERR_INVALID_REQUEST`. On success the six values are persisted, the engagement moves `QUALIFIED → SOW_ISSUED`, `burn_ratio` is set to 0.0 and `budget_posture` to `HEALTHY`, and `version` increments by 1.

Only the client can turn a proposal into a project. Signing is a `ClientContact` action, permitted only when the acting `X-User-ID` is the engagement's own `client_id`, and only from `SOW_ISSUED`. The signer supplies `signed_by_name`; the server stamps `signed_at` from the logical clock, moves the engagement `SOW_ISSUED → ACTIVE`, and increments `version` by 1. From here on, `ACTIVE` is the gate that almost everything else depends on: creating a milestone, creating a sprint, transitioning a sprint, opening a change request, submitting a change request, creating a release, recording a QA result, deciding acceptance on a release, and opening a retainer all require the parent engagement to be `ACTIVE`, and every one of those operations attempted against an engagement in any other status is rejected with `ERR_ENGAGEMENT_NOT_ACTIVE` (HTTP 409).

Closing is the delivery lead's prerogative and takes no payload. An engagement may be closed only from `ACTIVE`, and only when none of its sprints is currently `ACTIVE` — if any is, the close is refused with `ERR_ENGAGEMENT_HAS_ACTIVE_SPRINT` (HTTP 409). When the close succeeds, every ticket still sitting in `TODO` under a `PLANNED` sprint of that engagement is set to `CANCELLED`, the engagement moves `ACTIVE → CLOSED`, and `version` increments by 1. `CLOSED` is terminal.

### 3.2. Shaping the Delivery Plan: Milestones and Sprint Windows

Milestones are the fixed-fee billing skeleton of the engagement. A delivery lead adds one to an active engagement by supplying the `engagement_id`, a `sequence` (an ordering index of at least 1, unique among that engagement's milestones), a `title`, an `amount` strictly greater than zero at 2 decimal places, and a target `due_date`. A milestone is created `PLANNED`, with `accepted_at` null. There is a hard fiscal ceiling: the sum of `amount` across all milestones of an engagement may never exceed that engagement's `contract_value`. A milestone whose addition would push the sum over the contract value is refused with `ERR_MILESTONE_AMOUNT_EXCEEDS_CONTRACT` (HTTP 422). A `sequence` below 1, a duplicate `sequence` within the same engagement, or a non-positive `amount` are malformed bodies and draw `ERR_INVALID_REQUEST`.

Sprints are the execution windows. A delivery lead creates one against an active engagement with an `engagement_id`, a `name`, a `start_date`, an `end_date` and, optionally, a `milestone_id` tying the sprint to the milestone it works toward. **Sprint windows are half-open**: `start_date` is inclusive and `end_date` is exclusive. That convention is load-bearing. Two sprints of the same engagement overlap when the new sprint's `start_date` falls strictly before the existing sprint's `end_date` *and* the existing sprint's `start_date` falls strictly before the new sprint's `end_date`; exact adjacency — a new sprint starting on the very date an old one ends — is therefore permitted and is the normal way to chain sprints back to back. The overlap check is run only against sprints of the same engagement that are `PLANNED` or `ACTIVE`; `CLOSED` sprints are ignored and may be freely overlapped. A collision is rejected with `ERR_SPRINT_OVERLAP` (HTTP 409). If the supplied `milestone_id` names a milestone belonging to a different engagement, the create is rejected with `ERR_MILESTONE_ENGAGEMENT_MISMATCH` (HTTP 422) — the same rule guards release creation and invoice creation.

A sprint is created `PLANNED`, with `spend_frozen` false and `committed_hours` at 0. Its lifecycle is driven by a `target_status`. A `target_status` of `ACTIVE` advances a `PLANNED` sprint to `ACTIVE`, and at that instant the sprint's `spend_frozen` is seeded from the parent engagement's current `budget_posture`: it is set true when the posture is anything other than `HEALTHY`, and false when the posture is `HEALTHY`. A sprint activated into an already-strained engagement is therefore frozen from birth. A `target_status` of `CLOSED` moves an `ACTIVE` sprint to `CLOSED`, cancelling every ticket of that sprint still in `TODO` and recomputing `committed_hours` over the tickets that remain uncancelled. `CLOSED` is terminal. Any other requested transition — reopening a `CLOSED` sprint, closing a `PLANNED` one — draws `ERR_INVALID_TRANSITION`.

The sprint's `committed_hours` is at all times the sum of `estimated_hours` across every ticket of that sprint whose status is not `CANCELLED`.

### 3.3. The Ticket Board and the Blocker Graph

A delivery lead creates a ticket inside a sprint with a `sprint_id`, a `title`, an `estimated_hours` figure strictly greater than zero, an `assignee_user_id` naming the engineer who will own it, and optionally a `blocking_ticket_id` naming another ticket that must finish first. Tickets may be added to a sprint that is `PLANNED` or `ACTIVE`; only a `CLOSED` sprint refuses them, with `ERR_SPRINT_NOT_ACTIVE` (HTTP 409). A new ticket starts in `TODO` with `actual_hours` at 0, `variance_ratio` at 0 and `rework_rounds` at 0, and its creation recomputes the sprint's `committed_hours`.

The blocker graph is a self-referential structure and it must stay acyclic. A delivery lead may set or replace a ticket's blocker after creation by supplying a new `blocking_ticket_id`. Whether it arrives at creation or through a later re-pointing, a `blocking_ticket_id` that names the ticket itself, or that would close a loop reachable by walking the chain of `blocking_ticket_id` links, is rejected with `ERR_TICKET_CYCLE` (HTTP 422); the re-pointing is applied only after the cycle check clears.

Ticket movement is driven by a `target_status` and an optional `note`, and both engineers and delivery leads may drive it. Every ticket transition other than the two cancellations requires the owning sprint to be `ACTIVE` — a transition attempted while the sprint is `PLANNED` or `CLOSED` is refused with `ERR_SPRINT_NOT_ACTIVE`.

Starting work moves a ticket `TODO → IN_PROGRESS`, and it is the most heavily guarded transition on the board. It requires the sprint to be `ACTIVE`; it requires the sprint's `spend_frozen` to be false, failing with `ERR_SPRINT_SPEND_FROZEN` (HTTP 409) when the engagement's posture has frozen the sprint; and, when the ticket declares a `blocking_ticket_id`, it requires that blocker to have reached `DONE`, failing with `ERR_TICKET_BLOCKED` (HTTP 409) otherwise. Handing work to QA moves it `IN_PROGRESS → IN_QA` and needs only an `ACTIVE` sprint. A failed review sends it back with `IN_QA → REWORK`, which increments `rework_rounds` by 1 and is the entry point of the board's cycle: `IN_QA → REWORK → IN_PROGRESS → IN_QA`, repeatable without limit. Coming back out of rework — `REWORK → IN_PROGRESS` — carries the same two spend guards as the original start: the sprint must be `ACTIVE` and it must not be spend-frozen, so a ticket that entered rework after a freeze landed cannot be picked back up. Signing off moves the ticket `IN_QA → DONE` and requires an `ACTIVE` sprint plus a signer who is not the ticket's own `assignee_user_id`, as described in §2.10; on success the ticket's `variance_ratio` is recomputed. Cancellation is a delivery-lead-only move available from `TODO` and from `IN_PROGRESS`, sending the ticket to `CANCELLED` and recomputing the sprint's `committed_hours` in both cases; a ticket in `IN_QA`, `REWORK` or `DONE` cannot be cancelled. `DONE` and `CANCELLED` are terminal.

A ticket's `actual_hours` is at all times the sum of `hours` over its `APPROVED` time entries, and its `variance_ratio` is that `actual_hours` figure divided by its `estimated_hours`, rounded half up to 4 decimal places.

### 3.4. Logging Time and Reviewing It: the Hours Ledger

Only the ticket's own assignee may log time against it. An engineer submits a `ticket_id`, the `work_date` on which the work happened, the number of `hours`, an optional `billable` flag (defaulting to true), and an optional `note`. The server stamps `employee_user_id` from the acting `X-User-ID`; if that identifier does not equal the ticket's `assignee_user_id`, the entry is refused with `ERR_NOT_TICKET_ASSIGNEE` (HTTP 422). Time may only be logged while the owning sprint is `ACTIVE` (`ERR_SPRINT_NOT_ACTIVE` otherwise).

Three arithmetic gates guard the log. A single entry's `hours` must be strictly greater than 0 and no greater than 12, at 2 decimal places; outside that range it is a malformed body (`ERR_INVALID_REQUEST`). The `work_date` must fall inside the owning sprint's half-open window — on or after the sprint's `start_date` and strictly before its `end_date` — and an entry dated outside it is rejected with `ERR_WORK_DATE_OUT_OF_SPRINT` (HTTP 422). And across the whole system, no employee may accumulate more than 12 hours on any single calendar day: the sum of `hours` already logged by that same `employee_user_id` on that same `work_date`, counting entries in `SUBMITTED` and `APPROVED` status, plus the hours of the new entry, must not exceed 12 — a breach draws `ERR_DAILY_HOURS_EXCEEDED` (HTTP 422). Note the second gate counts submitted-but-unreviewed entries too, and note that it counts entries across *all* tickets and engagements, not just the one being logged against.

A new entry lands in `SUBMITTED` with `reviewed_by_user_id` null, and **nothing moves in the ledger until it is approved**. Review is a delivery lead's job. It carries a `decision` and an optional `note`, and the reviewer's `X-User-ID` must differ from the entry's `employee_user_id`. The entry's sprint must be `ACTIVE` at review time.

A `decision` of `REJECT` moves the entry `SUBMITTED → REJECTED`, records `reviewed_by_user_id` as the acting `X-User-ID`, and touches nothing else — the ticket's `actual_hours` is untouched and no burn is recomputed. `REJECTED` is terminal.

A `decision` of `APPROVE` moves the entry `SUBMITTED → APPROVED` and sets off a five-link cascade, each link caused by the one before it. First, the entry is marked `APPROVED` and `reviewed_by_user_id` is recorded. Second, that approval adds the entry's `hours` to the ticket's `actual_hours` and recomputes the ticket's `variance_ratio`. Third, the ticket's movement rolls up to the engagement, whose `approved_hours`, `burned_cost` and `burn_ratio` are recomputed. Fourth, the new `burn_ratio` recomputes the engagement's `budget_posture`. And fifth, the new posture propagates down: if it is `AT_RISK` or `OVERBURNED`, every sprint of that engagement currently in `ACTIVE` status has its `spend_frozen` set to true; if it is `HEALTHY`, every `ACTIVE` sprint has `spend_frozen` set to false. `PLANNED` and `CLOSED` sprints are never touched by the freeze cascade. The approval increments the engagement's `version` by 1.

Approval carries one further guard, and it fires before the cascade runs: **only for a billable entry**, the engagement's current `approved_hours` plus the entry's `hours` must not exceed the engagement's `budget_hours_cap`. A billable approval that would push the ledger past the cap is refused with `ERR_BUDGET_HOURS_EXCEEDED` (HTTP 422). A non-billable entry is exempt — it may be approved regardless of the cap, because it will never enter the burn.

Reversal is the exact inverse and is available only on an `APPROVED` entry. The delivery lead supplies a `reason`; the entry moves `APPROVED → REVERSED`, the entry's `hours` are subtracted back out of the ticket's `actual_hours` and `variance_ratio` is recomputed, the engagement's `approved_hours`, `burned_cost` and `burn_ratio` are recomputed, `budget_posture` is recomputed, and — should the posture return to `HEALTHY` — every `ACTIVE` sprint of the engagement has `spend_frozen` set back to false. The engagement's `version` increments by 1. `REVERSED` is terminal, and after a reverse the hours ledger must sit at precisely the numbers it held before the corresponding approval.

### 3.5. Burn, Posture and the Spend Freeze

The engagement's burn ledger is computed from time entries alone, and only two things qualify: an entry must be `APPROVED` **and** it must be billable. Entries in `SUBMITTED`, `REJECTED` or `REVERSED` status are excluded, as is any entry marked non-billable, and the exclusions apply no matter how large the entry is. The engagement's `approved_hours` is the sum of `hours` over the qualifying entries whose tickets roll up through their sprints to that engagement. Its `burned_cost` is that hours total multiplied by the engagement's `standard_hourly_rate`, with the single resulting product rounded half up to 2 decimal places — one rounding, on the aggregate, not per entry. Its `burn_ratio` is `burned_cost` divided by `contract_value`, rounded half up to 4 decimal places, where `contract_value` already carries whatever approved change requests have added to it. If no statement of work has been issued and `contract_value` is still null, both the ratio and the posture are held at their initial values — a ratio of 0.0 and a posture of `HEALTHY` — and no division is attempted. Likewise, when `approved_hours` is 0 the ratio is exactly 0.0.

`budget_posture` is a threshold read on that 4-decimal `burn_ratio`, and **both boundaries are inclusive**. A ratio of 1.0000 or above makes the engagement `OVERBURNED`. A ratio at or above 0.9000 but below 1.0000 makes it `AT_RISK` — a ratio of exactly 0.9000 *is* `AT_RISK`, not `HEALTHY`. Anything below 0.9000 is `HEALTHY`. The posture is recomputed immediately after the burn is recomputed, which is to say on every time-entry approval, every time-entry reversal, every change-request approval, and at SOW issue. Every recompute re-runs the freeze cascade in full: a non-`HEALTHY` posture freezes every `ACTIVE` sprint of the engagement by setting `spend_frozen` true, and a `HEALTHY` posture thaws every `ACTIVE` sprint by setting it false. The freeze is what stops a strained engagement from accruing more work: with `spend_frozen` true, no ticket in that sprint can be moved into `IN_PROGRESS`, whether from `TODO` or back out of `REWORK`.

There is a second, forward-looking view of the same numbers, and it exists precisely because the persisted one lags reality. A dedicated computed read on the engagement exposes both variants side by side. The **approved-only** variant — `approved_hours`, `burned_cost` and `burn_ratio` — is the persisted ledger described above, and it is the only variant that drives `budget_posture`, the spend freeze and the budget-cap check. The **committed** variant — returned as `committed_hours`, `committed_burned_cost` and `committed_burn_ratio` — widens the filter to entries in `SUBMITTED` **or** `APPROVED` status (still billable only, and still excluding `REJECTED` and `REVERSED`); `committed_hours` is their summed `hours`, `committed_burned_cost` is that total multiplied by `standard_hourly_rate` and rounded half up to 2 decimal places, and `committed_burn_ratio` is that cost divided by `contract_value` rounded half up to 4 decimal places. Whenever any billable entry is sitting unreviewed, the committed variant is strictly higher than the approved-only one — that is the whole point of it. The read also echoes the engagement's `engagement_id`, its current `budget_posture`, its `contract_value` and its `budget_hours_cap`, so a delivery lead can see the headroom and the pressure on the same screen.

### 3.6. Negotiating Scope: Change Requests

A delivery lead opens a change request against an active engagement by naming the `engagement_id`, a `title`, the additional `delta_hours` being requested (strictly greater than zero), a `rush` flag (defaulting to false), and the `expected_engagement_version` guard described in §2.7. The change request is created in `DRAFT` with `revision_rounds` at 0 and `quoted_amount` at 0, and — because the engagement's ledger has been touched — the engagement's `version` increments by 1.

Quoting happens at submit time, not at draft time, and it re-runs on every re-submit. Submitting sends a `DRAFT` change request (or one that has come back as `REVISION_REQUESTED`) to `SUBMITTED`, and the engagement must still be `ACTIVE` for the submit to be accepted. The quote is built in a strictly pinned order, and the order matters because the discount tier *looks* like it should key on the final figure but does not:

1. **Labour subtotal.** The requested `delta_hours` is multiplied by the engagement's `standard_hourly_rate` as it stands at submit time, and the product is rounded half up to 2 decimal places.
2. **Scope discount tier.** The tier is selected on the labour subtotal alone — never on the final quoted amount, which is larger. A labour subtotal of 20,000.00 or more earns a 10 percent scope discount; a labour subtotal of at least 5,000.00 but below 20,000.00 earns 5 percent; below 5,000.00 there is no discount at all. Both floors are inclusive: a labour subtotal of exactly 5,000.00 earns the 5 percent tier and a labour subtotal of exactly 20,000.00 earns the 10 percent tier. Change requests approved earlier on the same engagement do not aggregate into the tier — each change request is tiered on its own labour subtotal.
3. **Discounted labour.** The labour subtotal is reduced by the discount percentage (multiplied by one minus the discount rate), and the result is rounded half up to 2 decimal places.
4. **Project-management overhead.** The discounted labour is multiplied by 12 percent, and that overhead figure is rounded half up to 2 decimal places.
5. **Rush fee.** If and only if the `rush` flag is set, the discounted labour and the overhead are added together and that sum is multiplied by 15 percent, with the rush fee rounded half up to 2 decimal places. When `rush` is false the rush fee is exactly 0.00.
6. **Quoted amount.** `quoted_amount` is the plain sum of the discounted labour, the overhead and the rush fee. All three are already at 2 decimal places, so no further rounding is applied to the sum.

The client decides. A `ClientContact` whose `X-User-ID` matches the engagement's `client_id` supplies an `action` and an optional `note`, and only a `SUBMITTED` change request may be decided.

An `action` of `REQUEST_REVISION` sends it back: the change request moves `SUBMITTED → REVISION_REQUESTED` and `revision_rounds` increments by 1, opening the negotiation cycle `SUBMITTED → REVISION_REQUESTED → SUBMITTED`. That cycle is bounded. A change request may be sent back for revision at most **twice**; a third `REQUEST_REVISION` on the same change request — that is, one attempted while `revision_rounds` already stands at 2 — is refused with `ERR_CR_ROUND_LIMIT` (HTTP 409).

An `action` of `REJECT` moves it `SUBMITTED → REJECTED`, terminally, and changes nothing: the engagement's `contract_value` and `budget_hours_cap` are left exactly as they were.

An `action` of `APPROVE` requires the engagement to be `ACTIVE` and sets off a four-link cascade. First, the change request moves `SUBMITTED → APPROVED`, terminally. Second, that approval enlarges the engagement: the change request's `quoted_amount` is added to the engagement's `contract_value`, its `delta_hours` is added to the engagement's `budget_hours_cap`, and the engagement's `scope_hours_added` is recomputed as the sum of `delta_hours` across all of that engagement's `APPROVED` change requests. Third, the enlarged contract value forces a recomputation of `burn_ratio` — against the **new** `contract_value`, which is why an approval mechanically reduces the burn ratio even though not a single hour has moved. Fourth, `budget_posture` is recomputed from that new ratio, and if the engagement drops back to `HEALTHY`, every `ACTIVE` sprint of the engagement has `spend_frozen` set to false. Approving a change request is therefore the sanctioned way to unfreeze a team that has burned through its original budget. The approval increments the engagement's `version` by 1.

### 3.7. Staging, QA, Acceptance and Deployment

An engineer cuts a staging build against an active engagement by supplying the `engagement_id`, the `milestone_id` the build delivers, and a `version_label` such as "v1.2.0". The milestone must belong to the same engagement (`ERR_MILESTONE_ENGAGEMENT_MISMATCH` otherwise). The release is created in `BUILDING` with `qa_rounds` at 0, `defect_count` at 0, `accepted_at` null and `environment` null.

Recording a staging QA result is an engineer action on an active engagement and always increments `qa_rounds` by 1. The payload carries an `outcome` and a `defect_count`. An `outcome` of `PASS` requires the supplied `defect_count` to be exactly 0 and advances the release to `QA_PASSED` (from `BUILDING`, or from `REWORK` on a subsequent round), storing `defect_count` as 0. An `outcome` of `FAIL` requires the supplied `defect_count` to be at least 1, moves a `BUILDING` release to `REWORK`, and stores the supplied `defect_count` on the release — so `defect_count` always reflects the most recent QA result. A `PASS` submitted with a non-zero defect count, or a `FAIL` submitted with zero defects, does not match any legal transition and is refused with `ERR_INVALID_TRANSITION`.

Acceptance belongs to the client, and only from `QA_PASSED`. A `ClientContact` whose `X-User-ID` matches the engagement's `client_id` supplies an `action` and an optional `note`.

An `action` of `REJECT` sends the release back for another round: `QA_PASSED → REWORK`. The linked milestone is deliberately left alone — it stays `PLANNED` — and from `REWORK` the engineer's next passing QA result returns the release to `QA_PASSED`, completing the cycle `QA_PASSED → REWORK → QA_PASSED`.

An `action` of `ACCEPT` requires the engagement to be `ACTIVE` and triggers a three-link cascade that reaches all the way into billing. First, the release moves `QA_PASSED → ACCEPTED` and its `accepted_at` is stamped from the logical clock. Second, the milestone named by the release's `milestone_id` transitions `PLANNED → COMPLETED` and gets its own `accepted_at` stamped from the same clock. Third — and **only when the engagement's `billing_model` is `FIXED`** — a new invoice is created automatically for that milestone: a `DRAFT` invoice of kind `MILESTONE`, with its `lines`, `subtotal`, `tax` and `total` computed by the invoice rules of §3.8. This third link is conditional: on a `TIME_AND_MATERIALS` engagement, acceptance completes the milestone and creates nothing at all, and the finance officer raises time-and-materials invoices by hand. Because a cascade-created invoice arrives without the caller having asked for it, it is discovered by listing invoices filtered on the milestone.

Deployment closes the loop. An engineer deploys an `ACCEPTED` release by supplying the target `environment`, which is recorded on the release as it moves `ACCEPTED → DEPLOYED`. `DEPLOYED` is terminal.

### 3.8. Milestone Billing, Invoices, and the Compensating Void

Invoices are the finance officer's exclusive territory, and every one of them is computed server-side — the caller never supplies amounts. Creating an invoice takes the `engagement_id`, the `kind`, the `expected_engagement_version` guard of §2.7, and whichever of `milestone_id`, `retainer_id`, `period_start` and `period_end` the kind demands. The invoice is created in `DRAFT` with `issued_at` and `paid_at` null, and the engagement's `version` increments by 1.

The `kind` must be compatible with the engagement's `billing_model`. A `MILESTONE` invoice requires the engagement's `billing_model` to be `FIXED` and requires a `milestone_id`. A `TIME_AND_MATERIALS` invoice requires the engagement's `billing_model` to be `TIME_AND_MATERIALS` and requires both `period_start` and `period_end`. A `RETAINER` invoice requires a `retainer_id` whose own `engagement_id` matches the engagement being invoiced, and also requires both `period_start` and `period_end`. A mismatch between kind and billing model, or a missing kind-mandatory reference or period, is rejected with `ERR_INVOICE_KIND_MISMATCH` (HTTP 422). A milestone may carry at most one live invoice: if an invoice already exists for that `milestone_id` in `DRAFT`, `ISSUED` or `PAID` status, a second create is rejected with `ERR_DUPLICATE_MILESTONE_INVOICE` (HTTP 409) — only a `VOID` invoice frees the milestone for a fresh attempt.

The `lines` array is an ordered list of objects, each with a `label` and an `amount`, and how it is built depends on the kind. **Each line's `amount` is rounded half up to 2 decimal places on its own, and the `subtotal` is the plain sum of those already-rounded line amounts** — summing raw products and rounding once at the end is a different, wrong number.

For a `MILESTONE` invoice there is exactly one line: its `label` is the milestone's `title` and its `amount` is the milestone's `amount`.

For a `TIME_AND_MATERIALS` invoice, the eligible time entries are those that are `APPROVED`, are billable, whose `work_date` falls inside the **inclusive** window running from `period_start` through `period_end`, and whose ticket rolls up through its sprint to this engagement. Entries that are `SUBMITTED`, `REJECTED` or `REVERSED`, and non-billable entries of any status, are excluded. Note the boundary asymmetry with sprints: an invoicing period is closed at both ends, while a sprint window is closed at its start and open at its end. The eligible entries are grouped by ticket, and the tickets are emitted in ascending order of the ticket's `created_at`; the ticket identifier is never used for ordering. Each ticket produces one line whose `label` is the ticket's `title` and whose `amount` is that ticket's summed eligible `hours` multiplied by the engagement's `standard_hourly_rate`, rounded half up to 2 decimal places.

For a `RETAINER` invoice, the first line is labelled `Monthly retainer` and its `amount` is the retainer's `monthly_fee`. Then the SLA credits are netted: the `sla_credit_amount` values of every support incident under that retainer which is `RESOLVED` and whose `resolved_at` date falls inside the inclusive window from `period_start` through `period_end` are summed, and if that sum is greater than zero a second line labelled `SLA credit` is appended carrying the **negative** of the rounded credit sum. When the credit sum is zero, no credit line is appended at all.

From the `lines`, `subtotal` is the plain sum of the line amounts. `tax` is the subtotal multiplied by a tax rate of 8.25 percent, rounded half up to 2 decimal places; if the subtotal is negative — which an outsized SLA credit can produce — the tax is computed on zero rather than on the negative subtotal, so no negative tax is ever charged. `total` is `subtotal` plus `tax`, with no further rounding.

An invoice whose computed `lines` array comes out empty is still created — a time-and-materials period with no approved billable hours in it produces exactly that — but it can never be issued.

Issuing is what turns an invoice into money owed. Only a `DRAFT` invoice may be issued; the attempt is refused with `ERR_INVOICE_NO_LINES` (HTTP 422) if the invoice has no lines, and with `ERR_MILESTONE_NOT_COMPLETED` (HTTP 409) if it is a `MILESTONE` invoice whose milestone has not reached `COMPLETED`. On success the invoice moves `DRAFT → ISSUED`, `issued_at` is stamped from the logical clock, a `MILESTONE` invoice drags its milestone `COMPLETED → BILLED`, the engagement's `invoiced_amount` is recomputed as the sum of `subtotal` over the engagement's `ISSUED` and `PAID` invoices, the engagement's `billing_status` is recomputed from it per §2.9, and the engagement's `version` increments by 1.

Payment is recorded against an `ISSUED` invoice by supplying a `paid_amount` which must equal the invoice's `total` **exactly** — no partial payments, no overpayments; a mismatch is refused with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422). The invoice moves `ISSUED → PAID` and `paid_at` is stamped from the logical clock. `invoiced_amount` does not change, because `ISSUED` and `PAID` invoices count equally in the money ledger. `PAID` is terminal.

Voiding is the compensating action, and it is available both from `ISSUED` and from `DRAFT`. The finance officer supplies a `reason`. Voiding a `DRAFT` invoice simply moves it to `VOID` and changes no ledger — a draft was never counted. Voiding an `ISSUED` invoice unwinds the issue link by link: the invoice moves `ISSUED → VOID`; if it was a `MILESTONE` invoice, the milestone is walked back `BILLED → COMPLETED`; the engagement's `invoiced_amount` and `billing_status` are recomputed; and the engagement's `version` increments by 1. After a void, the money ledger, the billing status, and the milestone's status must all sit at exactly the values they held before the corresponding issue. A `PAID` invoice cannot be voided. `VOID` is terminal.

### 3.9. Maintenance Retainers and the Support SLA

Once a project is live, an account manager may open a maintenance retainer for the client against an active engagement. The payload names the `client_id`, the `engagement_id` the retainer maintains, the coverage `start_date` and `end_date`, a `monthly_fee` strictly greater than zero at 2 decimal places, the `included_hours` bundled into that fee (which may be zero but not negative), and an `sla_tier` of `GOLD`, `SILVER` or `BRONZE`.

**Retainer coverage windows are closed at both ends** — a retainer covers its `start_date` and its `end_date` and every day between — and a client may not hold two retainers back to back without a break. A cooldown buffer of 7 days is applied on both sides of every existing window: a new retainer collides with an existing retainer of the same client when the new `start_date` falls on or before the existing `end_date` plus 7 days *and* the existing `start_date` falls on or before the new `end_date` plus 7 days. A collision is rejected with `ERR_RETAINER_WINDOW_CONFLICT` (HTTP 409). The check is scoped to retainers of the same `client_id`; different clients never collide with one another.

Support incidents are raised by the client. A `ClientContact` supplies the `retainer_id`, a `severity` of `SEV1`, `SEV2` or `SEV3`, and a `summary`, and the incident is created `OPEN` with `opened_at` stamped from the logical clock. Incidents may only be raised while cover is live: the logical clock's current date must fall inside the retainer's closed window, on or after its `start_date` and on or before its `end_date`. An incident raised before cover starts or after it lapses is rejected with `ERR_RETAINER_WINDOW_INACTIVE` (HTTP 422).

An engineer responds first and resolves later. Responding takes an optional `note`, moves the incident `OPEN → RESPONDED`, and stamps `responded_at` from the logical clock. Resolving takes a `resolution_note`, moves the incident `RESPONDED → RESOLVED`, and stamps `resolved_at`. `RESOLVED` is terminal, and an incident may not skip the response step.

**Two different clocks measure the same span, and the incident's `severity` chooses which.** Both durations are measured from `opened_at` — `response_minutes` from `opened_at` to `responded_at`, and `resolution_minutes` from `opened_at` to `resolved_at`, *not* from the response. For a `SEV1` incident the coverage is round-the-clock and the **calendar clock** applies: every wall-clock minute of the span counts, including nights and weekends, and the elapsed time is converted to whole minutes by discarding any fractional minute. For a `SEV2` or `SEV3` incident the **business-hours clock** applies: only minutes falling inside the window from 09:00 up to (but not including) 17:00 UTC, on Mondays through Fridays, are counted; every minute outside that daily window and every minute of a Saturday or Sunday contributes nothing. To compute it, walk each UTC calendar day the span touches, from the day of the opening through the day of the response or resolution inclusive; skip Saturdays and Sundays; on every remaining day take the overlap between the span and that day's 09:00-to-17:00 UTC window, and add the whole minutes of overlap, discarding any fraction. An identical span therefore produces far fewer minutes under `SEV2` or `SEV3` than under `SEV1`, and can flip what looks like a breach into a non-breach.

Breach is judged by comparing those minute counts against the severity's targets, and the comparison is **strict** — a duration exactly equal to its target is not a breach. The response target is 60 minutes (one hour) for `SEV1`, 240 minutes (four hours) for `SEV2`, and 480 minutes (eight hours) for `SEV3`. The resolution target is 480 minutes (eight hours) for `SEV1`, 1,440 minutes (24 hours) for `SEV2`, and 2,880 minutes (48 hours) for `SEV3`. `sla_response_breached` is set true when `response_minutes` is strictly greater than the response target for the incident's severity, and it is computed at response time. `sla_resolution_breached` is set true when `resolution_minutes` is strictly greater than the resolution target, and it is computed at resolution time.

The money consequence lands at resolution. `sla_credit_amount` starts from a credit percentage of zero. If `sla_response_breached` is true, the retainer's tier percentage is added: 10 percent for a `GOLD` retainer, 5 percent for `SILVER`, 2 percent for `BRONZE`. If `sla_resolution_breached` is also true, the same tier percentage is added a second time — so a `GOLD` retainer with both clocks blown accrues 20 percent. The accumulated percentage is then capped at 25 percent, and `sla_credit_amount` is the retainer's `monthly_fee` multiplied by the capped percentage, rounded half up to 2 decimal places. An incident that breaches neither clock earns a credit of exactly 0.00, and incidents still `OPEN` or `RESPONDED` carry an `sla_credit_amount` of 0 because the credit is only computed at resolution. Those credits are what the retainer invoice of §3.8 later nets off, as a negative line, for every incident resolved inside the invoiced period.

## 4. Endpoint Definitions

All resources are addressed under a flat top-level namespace. Endpoints that mint a brand-new resource return **201 Created**; every other successful call — reads, lifecycle transitions, reviews, decisions, acceptances, issues, payments, voids and clock repositioning — returns **200 OK**. The table below is a routing summary only: request payloads, response payloads and side effects are specified by the narrative in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/clients` | Register a client company | AccountManager, PlatformAdmin |
| GET | `/clients/{id}` | Read a client | All roles |
| POST | `/engagements` | Create a lead for a client | AccountManager |
| GET | `/engagements/{id}` | Read an engagement including its computed burn ledger and version | All roles |
| GET | `/engagements` | List engagements, filterable by client, status and billing model | All roles |
| POST | `/engagements/{id}/qualify` | Qualify or disqualify a lead | AccountManager |
| POST | `/engagements/{id}/sow` | Issue the SOW/estimate: pins billing model, contract value, hour cap and blended rate | AccountManager |
| POST | `/engagements/{id}/sign` | Client signs the SOW; the engagement becomes ACTIVE | ClientContact |
| POST | `/engagements/{id}/close` | Close an active engagement | DeliveryLead |
| GET | `/engagements/{id}/burn-rate` | Computed read exposing both burn variants side by side | All roles |
| POST | `/milestones` | Add a billing milestone to an active engagement | DeliveryLead |
| GET | `/milestones/{id}` | Read a milestone | All roles |
| GET | `/milestones` | List milestones, filterable by engagement and status | All roles |
| POST | `/sprints` | Create a sprint window on an active engagement | DeliveryLead |
| GET | `/sprints/{id}` | Read a sprint | All roles |
| GET | `/sprints` | List sprints, filterable by engagement, milestone and status | All roles |
| POST | `/sprints/{id}/transition` | Activate or close a sprint | DeliveryLead |
| POST | `/tickets` | Create a ticket inside a sprint; may declare a blocking ticket | DeliveryLead |
| GET | `/tickets/{id}` | Read a ticket | All roles |
| GET | `/tickets` | List tickets, filterable by sprint, assignee, blocker and status | All roles |
| POST | `/tickets/{id}/transition` | Drive the ticket lifecycle | Engineer, DeliveryLead |
| POST | `/tickets/{id}/block` | Set or replace the ticket's blocking ticket | DeliveryLead |
| POST | `/time-entries` | Log time against a ticket | Engineer |
| GET | `/time-entries/{id}` | Read a time entry | All roles |
| GET | `/time-entries` | List time entries, filterable by ticket, employee and status | All roles |
| POST | `/time-entries/{id}/review` | Approve or reject a submitted time entry | DeliveryLead |
| POST | `/time-entries/{id}/reverse` | Reverse a previously approved time entry | DeliveryLead |
| POST | `/change-requests` | Open a scope change request against an active engagement | DeliveryLead |
| GET | `/change-requests/{id}` | Read a change request | All roles |
| GET | `/change-requests` | List change requests, filterable by engagement and status | All roles |
| POST | `/change-requests/{id}/submit` | Send (or re-send) the change request to the client; re-quotes it | DeliveryLead |
| POST | `/change-requests/{id}/decision` | Client approves, rejects, or requests a revision | ClientContact |
| POST | `/releases` | Cut a staging build for a milestone | Engineer |
| GET | `/releases/{id}` | Read a release | All roles |
| GET | `/releases` | List releases, filterable by engagement, milestone and status | All roles |
| POST | `/releases/{id}/qa-result` | Record a staging QA result | Engineer |
| POST | `/releases/{id}/acceptance` | Client accepts or rejects a QA-passed release | ClientContact |
| POST | `/releases/{id}/deploy` | Deploy an accepted release to an environment | Engineer |
| POST | `/invoices` | Create a DRAFT invoice; lines and totals are computed server-side | FinanceOfficer |
| GET | `/invoices/{id}` | Read an invoice including its computed lines | All roles |
| GET | `/invoices` | List invoices, filterable by engagement, milestone, retainer and status | All roles |
| POST | `/invoices/{id}/issue` | Issue a draft invoice to the client | FinanceOfficer |
| POST | `/invoices/{id}/pay` | Record full payment of an issued invoice | FinanceOfficer |
| POST | `/invoices/{id}/void` | Void an invoice (compensating action) | FinanceOfficer |
| POST | `/retainers` | Open a maintenance retainer for a client against an active engagement | AccountManager |
| GET | `/retainers/{id}` | Read a retainer | All roles |
| GET | `/retainers` | List retainers, filterable by client, engagement and SLA tier | All roles |
| POST | `/support-incidents` | Client raises a support incident under a retainer | ClientContact |
| GET | `/support-incidents/{id}` | Read a support incident with its SLA clock fields | All roles |
| GET | `/support-incidents` | List support incidents, filterable by retainer, status and severity | All roles |
| POST | `/support-incidents/{id}/respond` | First engineer response | Engineer |
| POST | `/support-incidents/{id}/resolve` | Resolve the incident; computes the SLA credit | Engineer |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |

"All roles" above means all six: `AccountManager`, `DeliveryLead`, `Engineer`, `ClientContact`, `FinanceOfficer` and `PlatformAdmin` — subject, for a `ClientContact`, to the scope confinement of §2.6.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_CLIENT_SCOPE_VIOLATION` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_CLIENT_NOT_FOUND` | 404 |
| `ERR_ENGAGEMENT_NOT_FOUND` | 404 |
| `ERR_MILESTONE_NOT_FOUND` | 404 |
| `ERR_SPRINT_NOT_FOUND` | 404 |
| `ERR_TICKET_NOT_FOUND` | 404 |
| `ERR_TIME_ENTRY_NOT_FOUND` | 404 |
| `ERR_CHANGE_REQUEST_NOT_FOUND` | 404 |
| `ERR_RELEASE_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_RETAINER_NOT_FOUND` | 404 |
| `ERR_INCIDENT_NOT_FOUND` | 404 |
| `ERR_STALE_ENGAGEMENT_VERSION` | 412 |
| `ERR_ENGAGEMENT_NOT_ACTIVE` | 409 |
| `ERR_SPRINT_NOT_ACTIVE` | 409 |
| `ERR_INVALID_TRANSITION` | 409 |
| `ERR_MILESTONE_NOT_COMPLETED` | 409 |
| `ERR_ENGAGEMENT_HAS_ACTIVE_SPRINT` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_NOT_TICKET_ASSIGNEE` | 422 |
| `ERR_TICKET_CYCLE` | 422 |
| `ERR_MILESTONE_ENGAGEMENT_MISMATCH` | 422 |
| `ERR_WORK_DATE_OUT_OF_SPRINT` | 422 |
| `ERR_SPRINT_OVERLAP` | 409 |
| `ERR_RETAINER_WINDOW_CONFLICT` | 409 |
| `ERR_RETAINER_WINDOW_INACTIVE` | 422 |
| `ERR_SPRINT_SPEND_FROZEN` | 409 |
| `ERR_TICKET_BLOCKED` | 409 |
| `ERR_CR_ROUND_LIMIT` | 409 |
| `ERR_INVOICE_KIND_MISMATCH` | 422 |
| `ERR_INVOICE_NO_LINES` | 422 |
| `ERR_DUPLICATE_MILESTONE_INVOICE` | 409 |
| `ERR_BUDGET_HOURS_EXCEEDED` | 422 |
| `ERR_DAILY_HOURS_EXCEEDED` | 422 |
| `ERR_MILESTONE_AMOUNT_EXCEEDS_CONTRACT` | 422 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 |
