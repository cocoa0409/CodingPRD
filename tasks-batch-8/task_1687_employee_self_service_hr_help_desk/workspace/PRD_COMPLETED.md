# Employee Self-Service HR Help Desk API — Product Requirements Document

## 1. Introduction

An HR shared services center sits between two pressures that pull in opposite directions. Employees want instant, self-service answers to routine questions — benefits enrollment, payroll deductions, address changes — and a frictionless path to a human being when self-service fails. The organization, meanwhile, must guarantee that sensitive matters such as harassment or medical accommodations are visible only to cleared case managers, that changes to payroll-relevant personal data survive fraud scrutiny, and that every mutation of an employee profile can be reconstructed later for audit. This document specifies the API behind that center: a searchable knowledge base with deflection telemetry, a tiered ticket queue governed by service-level clocks, a fraud-verified data-change pipeline with a complete audit trail, satisfaction measurement wired to coaching interventions, and seasonal staffing planning for predictable volume surges such as open enrollment.

All resources are mounted under the `/hr-helpdesk` prefix. The API recognizes eight acting roles, from the self-serving `Employee` to the platform-level `HRServicesAdmin`, and every rule below is written from the perspective of what those actors may do, in what order, and with what guarantees. Section 2 fixes the system-wide contract — envelope, pagination, clock, confidentiality, concurrency, and the order in which rejections surface; Section 3 walks the business workflows; Section 4 tabulates the endpoints; Section 5 catalogues the error codes.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The declared roles, spelled exactly as shown, are `Employee`, `HelpDeskAgent`, `SpecialistAgent`, `SensitiveCaseManager`, `KnowledgeManager`, `HRDataSteward`, `WorkforcePlanner`, and `HRServicesAdmin`. A request with missing or malformed headers, a role value outside this set, or — for the entity-backed roles below — an identifier that references no persisted row is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A caller whose role is not listed for the endpoint, or who violates a record-level ownership scope, is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Role charters:

- An `Employee` is the self-service user who owns tickets, data change requests, surveys, and article views; they create and work their own tickets, submit and verify their own data changes, submit their own surveys, and record article views, and they may read published knowledge articles, the category catalog, their own employee record, and their own audit trail.
- A `HelpDeskAgent` is the tier-1 generalist who triages, responds to, resolves, and escalates tickets, and may author knowledge base drafts.
- A `SpecialistAgent` is the tier-2 specialist who picks up escalated tickets belonging to their own team.
- A `SensitiveCaseManager` is the role that carries `SENSITIVE` clearance in day-to-day operations; permission to act on sensitive-category tickets is governed by clearance rather than by role, so any agent of any agent role holding `SENSITIVE` clearance may act on them (§2.7). Otherwise it shares the non-sensitive ticket toolkit with the other agent roles.
- A `KnowledgeManager` owns knowledge base editorial flow — publishing, returning drafts for rework, and archiving — and reads deflection metrics.
- An `HRDataSteward` is the compliance approver for data change requests and reads the audit trail.
- A `WorkforcePlanner` owns seasonal staffing windows and agent shifts, and reads service and satisfaction metrics.
- An `HRServicesAdmin` administers the platform: creating employees, teams, agents, categories, and SLA policies, driving employee lifecycle transitions, assigning tickets, and setting the logical clock.

Identity binding differs by role and is contractual. When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting `Employee`; ownership checks on any resource that references an employee — a ticket's `employee_id`, a survey's `employee_id`, a data change request's `employee_id`, an article view's `employee_id`, an audit entry's `employee_id` — compare that foreign key against `X-User-ID`, and list endpoints visible to this role are force-scoped to the caller's own records. When `X-User-Role` is `HelpDeskAgent`, `SpecialistAgent`, or `SensitiveCaseManager`, `X-User-ID` is the `id` of the acting `Agent`; checks that tie an action to a particular agent (for example, the self-assignment restriction described later) compare the supplied `agent_id` against `X-User-ID`. When `X-User-Role` is `KnowledgeManager`, `HRDataSteward`, `WorkforcePlanner`, or `HRServicesAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — as `published_by_user_id` on a knowledge article, `decided_by_user_id` on a data change request, `changed_by_user_id` on an audit entry, or `actor_user_id` on a ticket event — but never compares it to any entity's `id`.

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

---

### 2.3. Pagination

List endpoints accept two query parameters. `limit` caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` says how many items to skip and defaults to 0. A `limit` or `offset` that does not parse as an integer, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_VALIDATION`.

Unless a subsection below states a different ordering, every list endpoint returns resources sorted by `created_at` in ascending order. Two deliberate exceptions exist — knowledge base search results and the per-employee audit trail — and both are called out where those resources are described.

The `meta` object of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, with `has_more` true exactly when `offset` plus the number of items on the returned page is still below `total_count`. The filter query parameters named throughout §3 are exact-match equality filters on the named field; a boolean filter accepts only the literals `true` and `false` — any other value fails with `ERR_VALIDATION` — and an enum filter whose value lies outside the declared set fails with `ERR_INVALID_ENUM`.

### 2.4. Resource Identity and System-Managed Fields

Every primary resource exposes a uniform set of system-managed properties. The `id` is a server-minted UUID carrying no type prefix. `created_at` records the creation instant as an ISO 8601 UTC timestamp with three fractional digits; because all behavior is driven by the logical clock (§2.5), this stamp comes from that clock. `updated_at` follows the same format and refreshes on any modification. `version` is an integer that increments by one on every mutation of the resource, including mutations performed by the system itself — a recomputed flag that changes value, such as an employee's `has_pending_dcr` or an agent's `coaching_hold`, is a mutation and bumps the owning resource's `version` and `updated_at` exactly as a client-driven edit would. At creation a versioned resource starts at `version` 1 with `updated_at` equal to `created_at`.

Three resources are append-only records and carry a reduced property set: an article view, a ticket event, and an audit log entry each expose `id` and `created_at` only. For these three, both `updated_at` and `version` are absent.

### 2.5. The Logical Clock and Time-Driven Sweeps

Nothing in this API consults the wall clock. All deadlines, expiries, and scheduled transitions evaluate against a server-side logical clock whose startup default — before any explicit set — is exactly 2026-08-01T00:00:00Z. An admin-only test-driving capability lets an `HRServicesAdmin` advance the clock by supplying a target instant `to_iso8601`; the response reports the new logical time as `now_utc`. The target instant is not validated against the current logical time — the clock may be set to any instant, past or future.

Advancing the clock triggers four sweeps across the system. First, the SLA clock is re-evaluated for every ticket in a non-terminal workflow state (§3.6). Second, issued surveys whose validity has passed flip from `ISSUED` to `EXPIRED`. Third, tickets that have sat in `RESOLVED` for at least five days are auto-closed. Fourth, staffing windows whose start has been reached activate, and active windows whose end has passed complete. Independently of these sweeps, several reads evaluate lazily: every ticket read re-evaluates its `sla_status` against the current logical time, a staffing window read recomputes its coverage figures, and the satisfaction metric recomputes on read.

### 2.6. Cross-Entity Consistency and Cascading Mutations

The resource graph is flat: every resource is created at the top level of the API, and relationships are expressed through foreign keys carried in request payloads rather than through nested creation URLs — a ticket arrives with an `employee_id` and a `category_id`, an agent with a `team_id`, a shift with a `staffing_window_id`. Read paths may nest (for example, the SLA policy rows of one category, the events of one ticket, the fraud verification of one data change request, the audit trail of one employee); any such path is validated left to right, and the request is rejected with the `404` error of the first identifier that does not resolve — asking for the policy listing of a nonexistent category yields `ERR_CATEGORY_NOT_FOUND` before any policy lookup is attempted.

Single operations routinely mutate several resources in one consistent transaction, and every cascade stated in §3 is part of the contract: applying a data change request rewrites the employee profile, appends one audit entry per changed field, and cancels the employee's other pending requests; terminating an employee cancels their pending requests; publishing a revision supersedes the previous chain head; a coaching intervention releases an agent's open tickets. Each entity touched by a cascade has its own `version` incremented and its own `updated_at` refreshed, independently of the others.

### 2.7. Confidentiality and Sensitive-Case Handling

Certain categories — harassment, medical, and the like — are flagged sensitive at the category level. A ticket created in such a category copies that flag onto its own immutable `sensitive` marker at intake and keeps it for life.

Any write or action on a sensitive ticket requires the acting agent to hold `SENSITIVE` clearance; a `STANDARD`-clearance agent attempting one is rejected with `ERR_CONFIDENTIALITY_CLEARANCE_REQUIRED` (HTTP 403). This caller-side rule binds the agent roles only: callers in the opaque roles (an `HRServicesAdmin` assigning a sensitive ticket, for example) hold no clearance and are exempt from it, though resource-side clearance rules such as the assignee-clearance check of §3.5 still apply. Reads behave differently: rather than being rejected, they are masked. When the reader lacks `SENSITIVE` clearance and is not the owning employee, a sensitive ticket's `subject` and `description` are returned as the literal placeholder `[REDACTED]`, and the computed `masked` flag on the response is true; the owning employee and `SENSITIVE`-cleared staff see the full text with `masked` false. The `SensitiveCaseManager` role exists precisely to hold this clearance in day-to-day operations.

### 2.8. Service Calendars, Deadlines, and Numeric Precision

Each SLA policy row declares a `clock_mode`. Under `WALL_CLOCK` every elapsed minute counts, nights and weekends included. Under `BUSINESS_HOURS` only minutes inside 09:00–17:00 UTC on Monday through Friday count; Saturday and Sunday contribute zero, and deadline computation walks forward from the anchor instant consuming business minutes until the budgeted count is exhausted.

Two multiplier and rounding rules apply wherever SLA minutes are computed. A seasonal surge multiplier may stretch base policy minutes (§3.9), and after any multiplier is applied the result is rounded up to a whole number of minutes before being anchored to a timestamp.

All decimal rounding in the API is round-half-up, and each computed figure has a fixed precision: the knowledge-base deflection rate is reported to four decimal places; SLA attainment percentages to one decimal place; satisfaction weights to six decimal places, weighted score terms to two, and the reported means to two; staffing coverage hours to two decimal places. Coverage ratios themselves are compared exactly, without rounding, against their thresholds.

### 2.9. Optimistic Concurrency Control

Two write operations carry optimistic concurrency control, each keyed to the version of a parent entity.

`POST /hr-helpdesk/tickets/{id}/assign` requires the non-optional request field `expected_ticket_version`, carrying the caller's last observed `version` of the target Ticket. If that value does not equal the ticket's current `version` — because another writer has advanced the ticket since the caller last read it — the assignment is rejected with `ERR_STALE_TICKET_VERSION` (HTTP 412). Reassignment is legitimate product behavior: a ticket may be re-homed from one agent to another, so staleness is detected purely through this version check, never through any state precondition.

`POST /hr-helpdesk/data-change-requests` likewise requires the non-optional field `expected_employee_version`, carrying the caller's last observed `version` of the subject Employee. A mismatch with the employee's current `version` is rejected with `ERR_STALE_EMPLOYEE_VERSION` (HTTP 412): the new request would edit values the caller could not have seen, because a sibling request may have just been created or applied, flipping `has_pending_dcr` or writing profile fields.

Endpoints not named in this subsection do not accept a version field at all.

### 2.10. Validation Order and Error Precedence

When several checks could reject the same request, they are evaluated in the following fixed order, and the earliest failing tier determines the response:

1. **Authentication.** Headers present, role declared, and — for entity-backed roles — the supplied identifier resolving to an existing Employee or Agent row. Failures: `ERR_UNAUTHENTICATED` (401).
2. **Endpoint authorization and caller scope.** The caller's role is listed for the endpoint, and role-`Employee` callers stay inside their ownership scope. Failures: `ERR_FORBIDDEN_ROLE` (403).
3. **Request shape.** Required fields present, enum values inside their declared sets, types valid, and the sub-fields of a data change request's `new_values` complete for its `change_type`. Failures: `ERR_VALIDATION` or `ERR_INVALID_ENUM` (400).
4. **Existence.** Path identifiers resolve left to right, then body foreign keys resolve — `employee_id`, `category_id`, `agent_id`, `article_id`, `team_id`, `staffing_window_id`, `ticket_id` as applicable. Failures: `ERR_EMPLOYEE_NOT_FOUND`, `ERR_AGENT_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_CATEGORY_NOT_FOUND`, `ERR_ARTICLE_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_DCR_NOT_FOUND`, `ERR_SURVEY_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, or `ERR_SHIFT_NOT_FOUND` (all 404). A missing SLA policy row for the ticket's category-and-priority pair at intake is also raised here, as `ERR_SLA_POLICY_NOT_FOUND` (404).
5. **Record-level ownership.** For an `Employee` caller acting on a specific located resource, the resource's owning `employee_id` must equal the caller's `X-User-ID`. Failures: `ERR_FORBIDDEN_ROLE` (403).
6. **State.** The target entity must sit in a from-state of the requested transition. Failures: `ERR_TICKET_INVALID_STATE`, `ERR_DCR_INVALID_STATE`, `ERR_ARTICLE_INVALID_STATE`, `ERR_SURVEY_INVALID_STATE`, `ERR_WINDOW_INVALID_STATE`, `ERR_SHIFT_INVALID_STATE`, or `ERR_EMPLOYEE_INVALID_STATE` (all 409). A verification attempt against an already `LOCKED` fraud verification raises `ERR_FRAUD_VERIFICATION_LOCKED` (409) at this tier, ahead of the generic data-change state error.
7. **Business safety.** Confidentiality clearance on writes to sensitive tickets (`ERR_CONFIDENTIALITY_CLEARANCE_REQUIRED`, 403); the fraud gate on approval (`ERR_FRAUD_VERIFICATION_REQUIRED`, 409); the employee-active gate on data change creation and approval (`ERR_EMPLOYEE_INACTIVE`, 422); and the segregation-of-duties rules (`ERR_AUTHOR_CANNOT_PUBLISH`, `ERR_SELF_APPROVAL_FORBIDDEN`, `ERR_VERIFIER_CANNOT_APPROVE`, all 403).
8. **Business constraints.** Capacity (`ERR_AGENT_AT_CAPACITY`, 409), tier match (`ERR_AGENT_TIER_INSUFFICIENT`, 409), specialist pool emptiness (`ERR_NO_ELIGIBLE_SPECIALIST`, 422), interval overlaps (`ERR_SHIFT_OVERLAP`, `ERR_WINDOW_OVERLAP`, 409), uniqueness (`ERR_SLA_POLICY_DUPLICATE`, `ERR_DUPLICATE_DATA_CHANGE_PENDING`, `ERR_DUPLICATE_EMPLOYEE_NUMBER`, `ERR_DUPLICATE_CATEGORY_CODE`, 409), and the two optimistic-concurrency checks (`ERR_STALE_TICKET_VERSION`, `ERR_STALE_EMPLOYEE_VERSION`, 412).
9. **Temporal rules.** Reopen window (`ERR_REOPEN_WINDOW_PASSED`, 409), survey expiry (`ERR_SURVEY_EXPIRED`, 409), and interval bounds (`ERR_INVALID_TIME_RANGE`, `ERR_SHIFT_OUTSIDE_WINDOW`, 422).
10. **Referential usability.** Referenced objects must be usable for the purpose: the cited resolution article published (`ERR_RESOLUTION_ARTICLE_NOT_PUBLISHED`, 422), the intake category active (`ERR_CATEGORY_INACTIVE`, 422), viewed or superseded articles in the required state (`ERR_ARTICLE_INVALID_STATE`, 409), and a shift's window still accepting shifts (`ERR_WINDOW_INVALID_STATE`, 409).

### 2.11. Segregation of Duties

Three separation rules keep any single person from controlling a sensitive decision end to end; all three are enforced in the business-safety tier above. A knowledge article's author may not publish that article (`ERR_AUTHOR_CANNOT_PUBLISH`). An employee may not approve or reject their own data change request (`ERR_SELF_APPROVAL_FORBIDDEN`). And the person who satisfied a request's fraud verification may not approve that same request (`ERR_VERIFIER_CANNOT_APPROVE`). Section 3 places each rule in its workflow context.

## 3. Business Logic & Workflows

### 3.1. People, Teams, and the Agent Roster

Everything in the help desk hangs off the employee roster. An `HRServicesAdmin` enrolls an employee with an `employee_number` (the unique HRIS number; a duplicate is rejected with `ERR_DUPLICATE_EMPLOYEE_NUMBER`), a `full_name`, a work `email`, and optionally a `manager_id` pointing at another employee — null at the top of the management tree, rejected with `ERR_EMPLOYEE_NOT_FOUND` when it references no existing employee, and load-bearing later because the manager of record is one of the two fraud-verification channels for data changes. An initial `status` may be supplied — any of the three declared values is accepted — but defaults to `ACTIVE`.

Two blocks of the employee profile are deliberately closed to direct writes. The address block — `address_line1`, `city`, `region`, `postal_code` — and the direct-deposit block — `bank_routing_number`, `bank_account_number`, and `bank_account_type` (one of `CHECKING` or `SAVINGS`) — start null and are written only when a data change request is applied (§3.7). Two further fields are maintained derivations: `has_pending_dcr`, initially false, is true exactly while any data change request of the employee sits in `PENDING_VERIFICATION` or `PENDING_APPROVAL`, and is maintained on request creation, approval, rejection, and cancellation — every flip bumps the employee's `version`; `open_ticket_count` is the computed count of the employee's tickets in `NEW`, `TRIAGED`, `IN_PROGRESS`, `PENDING_EMPLOYEE`, `ESCALATED`, or `REOPENED`.

The employee lifecycle is a small machine on `status`: `ACTIVE` and `ON_LEAVE` transition back and forth under an `HRServicesAdmin`, and either may move to `TERMINATED`, which is terminal — any attempt to leave `TERMINATED`, and indeed any transition not listed here (including one to the employee's current status), fails with `ERR_EMPLOYEE_INVALID_STATE`. Termination cascades: every data change request of the employee still in `PENDING_VERIFICATION` or `PENDING_APPROVAL` moves to `CANCELLED`, and `has_pending_dcr` is recomputed. Open tickets are deliberately not cancelled; they remain actionable work items for the queue. The employee list can be narrowed with the `status` and `manager_id` filters, and reading a single employee is available to staff and — for their own record only — to the employee.

Teams group agents for escalation routing and staffing. A team is created with a unique `name` (a duplicate is rejected with `ERR_VALIDATION`) and an optional free-text `description`.

Agents are the queue's workforce. Each agent is enrolled with a `display_name`, a work `email`, a skill `tier` (`T1` generalist or `T2` specialist), a `clearance` (`STANDARD` by default, or `SENSITIVE` for confidential casework), a home `team_id`, a `capacity_max` (the maximum number of open tickets assigned at once, defaulting to 10; a value of 0 means the agent can never be assigned), and an `active` flag (default true) — inactive agents are excluded from every selector and from assignment. Two computed fields describe the agent's live load and health: `assigned_open_count` counts tickets currently assigned to the agent in `TRIAGED`, `IN_PROGRESS`, `PENDING_EMPLOYEE`, or `ESCALATED`, plus tickets still in `NEW` — a combination that occurs only through the sensitive auto-assignment at intake described in §3.4; and `rolling_csat`, the recency-weighted satisfaction mean of §3.8, which stays null until the agent has at least one submitted survey inside the measurement window. A third, system-managed flag, `coaching_hold`, starts false and tracks the coaching rule of §3.8. The agent list supports the filters `team_id`, `tier`, `clearance`, and `active`; reading one agent returns the computed `assigned_open_count`, `rolling_csat`, and `coaching_hold` alongside the stored fields.

### 3.2. Categories and Service-Level Policies

A ticket category is created with a unique `code` (a duplicate is rejected with `ERR_DUPLICATE_CATEGORY_CODE`), a human-readable `name`, an `is_sensitive` flag (default false) that drives the confidentiality behavior of §2.7, a `specialist_team_id` naming the team whose tier-2 agents receive escalations for the category, and an `active` flag (default true). Retiring a category stops new intake — submitting a ticket into an inactive category fails with `ERR_CATEGORY_INACTIVE` — while tickets already in flight are unaffected. The category list, visible to all roles, can be filtered by `active` and `specialist_team_id`.

Service-level policy is expressed as one row per category-and-priority combination. A row carries the `category_id`, the `priority` it governs (one of `P1`, `P2`, `P3`, `P4`), a `first_response_minutes` budget and a `resolution_minutes` budget (both strictly positive), and a `clock_mode` — `WALL_CLOCK` by default, or `BUSINESS_HOURS`, with the semantics of §2.8. Only one row may exist for a given (`category_id`, `priority`) pair; a second insert is rejected with `ERR_SLA_POLICY_DUPLICATE`. Rows are listable globally with the `category_id` and `priority` filters, and per category through the category's own policy listing. Intake depends on this catalog: if no row exists for the ticket's category and priority, the ticket is not created and the request fails with `ERR_SLA_POLICY_NOT_FOUND`.

### 3.3. Knowledge Base Authorship, Review, and Revision Chains

Knowledge articles begin as drafts authored by a `KnowledgeManager`, `HelpDeskAgent`, or `SpecialistAgent`. Authoring supplies a `title`, a markdown `body`, the `category_id` the article is meant to deflect tickets for, an optional list of search `keywords` (empty by default), and an optional `supersedes_article_id` declaring the draft a revision of an existing article. A revision target must be `PUBLISHED` at the moment the draft is created; targeting anything else fails with `ERR_ARTICLE_INVALID_STATE`, while a null `supersedes_article_id` marks the draft the root of a new chain. The server stamps `author_user_id` from the caller's `X-User-ID` and starts the article in `DRAFT`.

Review is a loop with one exit. Submitting a draft for review moves `DRAFT` to `IN_REVIEW` and may be done by the author or by any `KnowledgeManager`. A `KnowledgeManager` may return an in-review article to `DRAFT` for rework. Publishing is restricted to a `KnowledgeManager` who is not the author: the author attempting to publish their own article is rejected with `ERR_AUTHOR_CANNOT_PUBLISH`. A successful publish stamps `published_at` and `published_by_user_id`. When the article is a revision, publishing has an atomic extra step: the article named by `supersedes_article_id` must currently be `PUBLISHED` — if the chain head has moved on, the publish fails with `ERR_ARTICLE_INVALID_STATE` — and on success the referenced article flips from `PUBLISHED` to `SUPERSEDED` in the same transaction, so each revision chain conserves exactly one published head; both articles' versions increment. Finally, a `KnowledgeManager` may archive a published article, moving `PUBLISHED` to `ARCHIVED` and removing it from employee-visible search results. `SUPERSEDED` and `ARCHIVED` are terminal.

Employees meet the knowledge base through search. The article list accepts a query string `q`, matched as a case-insensitive substring over `title` and `keywords`, plus the filters `category_id`, `status`, and `supersedes_article_id`. Callers in the `Employee` role see `PUBLISHED` articles only, and an employee asking directly for a non-published article receives `ERR_ARTICLE_NOT_FOUND`, indistinguishable from absence. Search ordering is one of the two exceptions to the default sort: articles are returned by `view_count` descending, then `created_at` descending. Two computed counters track each article's performance: `view_count`, the number of recorded article views, and `deflection_fail_count`, the number of those views whose `deflection_outcome` is `TICKET_CREATED` (§3.4).

### 3.4. Self-Service Viewing, Ticket Intake, and Deflection Linkage

Before a ticket ever exists, the typical journey runs through the knowledge base, and each visit is metered. An `Employee` records an article view by supplying the viewed `article_id`; the article must be `PUBLISHED`, and the referential rule rejects unusable targets with `ERR_ARTICLE_INVALID_STATE`. The server stamps the view with the caller's identity as `employee_id` and with `viewed_at` taken from the logical clock, equal to the record's `created_at`; the `deflection_outcome` starts as `NONE`. Article views are append-only telemetry, and the article's `view_count` is recomputed as views accumulate. Staff can list views with the `employee_id`, `article_id`, and `deflection_outcome` filters; an employee reads back only their own. Reading a view id that does not resolve fails with `ERR_ARTICLE_NOT_FOUND`.

When self-service fails, the employee opens a ticket with the `employee_id` of the requester — which must equal the caller's `X-User-ID` — the target `category_id`, a one-line `subject`, a full `description`, and an optional `priority` that defaults to `P3`. Intake enforces the catalog rules of §3.2: an inactive category fails with `ERR_CATEGORY_INACTIVE`, and a missing policy row fails with `ERR_SLA_POLICY_NOT_FOUND` before any ticket exists. On acceptance the server fixes the ticket's scaffolding: `sensitive` is copied from the category's `is_sensitive` and is immutable thereafter; `tier` starts at `T1`; `workflow_status` opens at `NEW`; `sla_status` opens at `ON_TRACK`; `escalation_count` and `reopen_count` start at zero; `assigned_agent_id`, `source_article_id`, `resolution_article_id`, `resolution_summary`, `first_responded_at`, `resolved_at`, and `closed_at` all start null. A `CREATED` event is appended to the ticket's log with the caller as `actor_user_id`, and the employee's `open_ticket_count` is recomputed.

Both SLA deadlines are computed at creation. The policy row for the ticket's category and priority supplies the base minutes; then a surge multiplier is determined — normally 1.0, but if the category's specialist team has an `ACTIVE` staffing window whose inclusive bounds cover the creation instant, that window's `sla_multiplier` applies instead (the window overlap rule of §3.9 guarantees at most one such active window per team). Each budget is multiplied by the surge and rounded up to a whole number of minutes. Under `WALL_CLOCK`, `first_response_due_at` and `resolution_due_at` are simply the creation instant plus the effective minutes. Under `BUSINESS_HOURS`, the computation walks forward from creation consuming only minutes inside 09:00–17:00 UTC Monday through Friday — weekends contribute zero — so an identical creation instant yields a strictly later deadline whenever the span touches non-business time.

Intake also performs the deflection link. The server scans the caller's recent article views for candidates: views by the same employee, of articles in the ticket's category, viewed no earlier than sixty minutes before ticket creation (the boundary included), whose `deflection_outcome` is still `NONE`. If candidates exist, the one with the latest `viewed_at` is chosen — ties broken by the later view `created_at` — and is consumed: the ticket's `source_article_id` is set to that article, and the view's `deflection_outcome` flips to `TICKET_CREATED`, feeding both the article's `deflection_fail_count` and the deflection-rate metric of §3.6.

A ticket in a sensitive category gets one more piece of automation at intake: the system attempts an immediate assignment, selecting among agents who are active, hold `SENSITIVE` clearance, and are under capacity — `assigned_open_count` strictly below `capacity_max` — ranked by `assigned_open_count` ascending with ties broken by the earlier agent `created_at`. The winner becomes the `assigned_agent_id` while the ticket remains `NEW`, which is why `NEW` tickets contribute to an agent's `assigned_open_count`. An empty pool simply leaves the ticket unassigned in `NEW`, waiting for triage. Non-sensitive intake never auto-assigns.

### 3.5. Working the Queue: Triage, Assignment, Escalation, Resolution

A new ticket first meets a human at triage, which moves `NEW` to `TRIAGED` and is performed by a `HelpDeskAgent` or a `SensitiveCaseManager`; for a sensitive ticket the caller must hold `SENSITIVE` clearance, otherwise the call fails with `ERR_CONFIDENTIALITY_CLEARANCE_REQUIRED`. Triage accepts an optional `priority` override: when one is supplied, the server re-looks-up the policy row for the category and the new priority — a missing row fails the triage with `ERR_SLA_POLICY_NOT_FOUND` — and recomputes both `first_response_due_at` and `resolution_due_at` from the original creation instant, still using the surge multiplier that was in effect at creation. A `TRIAGED` event is appended and the ticket's `version` increments.

Assignment moves a ticket from any of `NEW`, `TRIAGED`, `ESCALATED`, or `REOPENED` to `IN_PROGRESS`. The call names an `agent_id` and must carry the OCC field `expected_ticket_version` per §2.9, with mismatches rejected as `ERR_STALE_TICKET_VERSION`. The assignee must exist (otherwise `ERR_AGENT_NOT_FOUND`) and be active — an inactive agent fails the assignment pre-checks with `ERR_AGENT_AT_CAPACITY`. Three fit checks follow: the assignee's `assigned_open_count` must be strictly below their `capacity_max` (otherwise `ERR_AGENT_AT_CAPACITY`, and recall that a `capacity_max` of 0 renders an agent unassignable); a sensitive ticket accepts only an assignee whose `clearance` is `SENSITIVE` (otherwise `ERR_CONFIDENTIALITY_CLEARANCE_REQUIRED`); and the assignee's `tier` must equal the ticket's current `tier` (otherwise `ERR_AGENT_TIER_INSUFFICIENT`). `SpecialistAgent` and `SensitiveCaseManager` callers may only self-assign — the supplied `agent_id` must equal the caller's `X-User-ID`, and attempts to assign someone else are rejected as scope violations with `ERR_FORBIDDEN_ROLE` — while `HelpDeskAgent` and `HRServicesAdmin` may assign any eligible agent. The assignee-side checks are evaluated in a fixed order: first the assignee-clearance check for a sensitive ticket, then the active and capacity checks, then tier match, and the `expected_ticket_version` comparison is evaluated last of all, only after every fit check has passed. The effects are: `assigned_agent_id` is set, an `ASSIGNED` event is appended (an `UNASSIGNED` and `ASSIGNED` pair when a prior agent is being replaced), and the ticket's `version` increments.

Once work is under way, responding records an agent reply without moving the workflow: it is valid from `TRIAGED`, `IN_PROGRESS`, or `ESCALATED`, requires the sensitive-clearance rule where applicable, and carries a free-text `body`. The first response stamps `first_responded_at` — later responses leave it untouched — and a `BREACHED_RESPONSE` status, once latched, is not cleared by responding. Each response appends a `RESPONDED` event and bumps the version. When an agent needs more from the requester, requesting information moves `IN_PROGRESS` to `PENDING_EMPLOYEE` with a `body` and an `INFO_REQUESTED` event; the owning employee answers with a free-text `body` of their own, which moves `PENDING_EMPLOYEE` back to `IN_PROGRESS` with an `INFO_PROVIDED` event. Only the owner may provide information — a caller whose `X-User-ID` differs from the ticket's `employee_id` is rejected with `ERR_FORBIDDEN_ROLE`.

Escalation hands a ticket to the specialists. A `HelpDeskAgent` escalates from `TRIAGED` or `IN_PROGRESS`, optionally recording a `reason`; the ticket must still be tier `T1`, and escalating an already-`T2` ticket fails with `ERR_TICKET_INVALID_STATE`. The server then runs the specialist selector over agents whose `team_id` equals the category's `specialist_team_id`, who are tier `T2`, active, under capacity, and — when the ticket is sensitive — `SENSITIVE`-cleared. An empty pool rejects the escalation with `ERR_NO_ELIGIBLE_SPECIALIST` and leaves the ticket exactly as it was. Otherwise the winner, ranked by `assigned_open_count` ascending with ties broken by earlier agent `created_at`, becomes the `assigned_agent_id`; the ticket's `tier` flips to `T2`, `escalation_count` increments, and the ticket lands in `ESCALATED`. Crucially, escalation does not touch the SLA clocks: `first_response_due_at`, `resolution_due_at`, and `sla_status` carry over unchanged. An `ESCALATED` event records the hand-off.

Resolution moves `IN_PROGRESS` or `REOPENED` to `RESOLVED` under the same clearance rule, and the agent supplies a `resolution_summary` plus an optional `resolution_article_id` citing the knowledge article that solved the case — the cited article must be `PUBLISHED`, otherwise the resolve fails with `ERR_RESOLUTION_ARTICLE_NOT_PUBLISHED`. The server stamps `resolved_at`, then sets `sla_status` to `MET` when the resolution instant is no later than `resolution_due_at`, and to `BREACHED_RESOLUTION` when it is strictly later — in both cases overwriting whatever of `ON_TRACK`, `AT_RISK`, or `BREACHED_RESPONSE` stood before. The first resolution of a ticket — and only the first — issues exactly one satisfaction survey to the requester (§3.8). A `RESOLVED` event closes out the work.

The employee retains three exits of their own. Reopening takes `RESOLVED` back to `REOPENED`: it requires the owner, a `reason`, and timeliness — the reopen must arrive no later than seventy-two hours after `resolved_at`, with the boundary instant itself still allowed; a later attempt fails with `ERR_REOPEN_WINDOW_PASSED`. Reopening increments `reopen_count`, resets `sla_status` to `ON_TRACK`, and re-anchors `resolution_due_at` from the reopen instant as that instant plus the policy's resolution minutes scaled by the creation-time surge multiplier, rounded up to whole minutes — the policy row is re-looked-up at reopen time, and if it no longer exists the reopen fails with `ERR_SLA_POLICY_NOT_FOUND`; no new survey is created, because a ticket issues only one ever. Closing moves `RESOLVED` to `CLOSED` — either manually by the owner, or by the system itself once the ticket has sat resolved for at least five days, evaluated when the clock advances; both paths stamp `closed_at` and append an event, `CLOSED` for the manual path and `AUTO_CLOSED` for the sweep. Cancelling moves `NEW` or `TRIAGED` to `CANCELLED` at the owner's request, optionally with a `reason`, and clears `assigned_agent_id`. `CLOSED` and `CANCELLED` are the ticket's terminal states. Ownership failures on any of these employee actions surface as `ERR_FORBIDDEN_ROLE`, and attempting any transition from a state that does not support it surfaces as `ERR_TICKET_INVALID_STATE`.

Every state-moving call appends to the ticket's event log. Each entry records the `ticket_id`, the `actor_user_id` (the literal string `system` for clock-driven events), the `event_type`, the `from_state` and `to_state` of the transition (null where an event has no workflow dimension), and a `note` carrying the reason or body supplied with the triggering call where one exists. Concretely: `CREATED` carries a null `from_state` and `to_state` `NEW`; `RESPONDED` carries the ticket's unchanged current state in both `from_state` and `to_state`; `SLA_BREACH` carries null in both fields; and the `note` of a `RESOLVED` event carries the supplied `resolution_summary`. The log distinguishes fifteen event types: `CREATED`, `TRIAGED`, `ASSIGNED`, `UNASSIGNED`, `RESPONDED`, `INFO_REQUESTED`, `INFO_PROVIDED`, `ESCALATED`, `RESOLVED`, `REOPENED`, `CLOSED`, `CANCELLED`, `AUTO_CLOSED`, `SLA_BREACH`, and `COACHING_RELEASE`. The owner and the agent roles read the log in chronological order, `created_at` ascending. The ticket list itself can be narrowed by requester (`employee_id`), current assignee (`assigned_agent_id`), `category_id`, either status dimension (`workflow_status` or `sla_status`), `priority`, or either article link (`source_article_id`, `resolution_article_id`); callers in the `Employee` role see only their own tickets.

### 3.6. The SLA Clock, Breach Evaluation, and Performance Metrics

Parallel to the workflow, every ticket carries a second status dimension, `sla_status`, which opens at `ON_TRACK` and ends at `MET` or `BREACHED_RESOLUTION`. It is re-evaluated whenever the logical clock advances and, lazily, on every read of a ticket or the ticket list, so what a client observes always reflects the current logical time. Evaluation walks a fixed severity chain over every ticket whose `workflow_status` is one of `NEW`, `TRIAGED`, `IN_PROGRESS`, `PENDING_EMPLOYEE`, `ESCALATED`, or `REOPENED`: if the current time is strictly past `resolution_due_at`, the ticket moves to `BREACHED_RESOLUTION`; otherwise, if no agent has responded yet (`first_responded_at` still null) and the current time is strictly past `first_response_due_at`, it moves to `BREACHED_RESPONSE`; otherwise, if the fraction of the resolution budget already consumed — elapsed time since creation divided by the full span from creation to `resolution_due_at` — has reached three-quarters, the ticket moves to `AT_RISK`; otherwise it remains `ON_TRACK`. This evaluation order pins the breach priority: a resolution breach outranks a response breach, which outranks at-risk.

Two boundary rules are exact. A consumed fraction of exactly 0.75 flips the ticket to `AT_RISK` — the threshold is inclusive — while the current time landing exactly on a deadline is not a breach, because breaching requires the deadline to be strictly in the past. Severity never heals backwards: the clock can move a ticket from `ON_TRACK` or `AT_RISK` into `BREACHED_RESPONSE`, and from `ON_TRACK`, `AT_RISK`, or `BREACHED_RESPONSE` into `BREACHED_RESOLUTION`, but never in reverse. Each breach transition appends an `SLA_BREACH` event whose `note` names the new state, and bumps the ticket's `version`. The dimension freezes entirely once a ticket is `CLOSED` or `CANCELLED`. Resolution is the only manual influence on this dimension, landing the ticket in `MET` or `BREACHED_RESOLUTION` as described in §3.5.

Three read-only metrics aggregate the queue's performance. The deflection metric for a `category_id` considers article views of that category's articles whose `viewed_at` falls inside the trailing thirty days, both ends inclusive: it reports the category, the `window_days`, the total `view_count`, the `ticket_created_count` of views whose `deflection_outcome` is `TICKET_CREATED`, and the `deflection_rate` — one minus the ratio of ticket-creating views to all views, rounded half-up to four decimal places, and exactly 0.0 when there are no views at all. The SLA attainment metric for a `category_id` pools the category's tickets that have reached resolution at least once — `resolved_at` set, with `workflow_status` currently `RESOLVED`, `REOPENED`, or `CLOSED`, so a reopened ticket counts once by its current `sla_status` — and reports `met_count` of tickets at `MET`, `breached_count` at `BREACHED_RESOLUTION`, and `attainment_pct`: one hundred times the met count divided by the sum of the two, rounded half-up to one decimal place, and exactly 0.0 when the pool is empty. The satisfaction metric for an `agent_id` recomputes the figures of §3.8 on read, reporting `window_days`, the in-window `survey_count`, the `simple_mean`, and the `recency_weighted_mean`. Each metric endpoint takes its subject as a required query parameter (`category_id` or `agent_id`): a missing or empty parameter fails with `ERR_VALIDATION`, and one referencing no persisted row fails with the matching 404 (`ERR_CATEGORY_NOT_FOUND` or `ERR_AGENT_NOT_FOUND`).

### 3.7. Employee Data Changes and Fraud Verification

Payroll-relevant profile data never changes by direct edit; it changes through a data change request. An employee submits one naming the subject `employee_id` — which must equal the caller's `X-User-ID` — a `change_type` of `ADDRESS` or `DIRECT_DEPOSIT`, a `new_values` object carrying the replacement fields, and the OCC field `expected_employee_version` per §2.9, whose mismatch with the employee's current `version` fails the submission with `ERR_STALE_EMPLOYEE_VERSION`. The `new_values` object must be complete for its type: an address change requires `address_line1`, `city`, `region`, and `postal_code`; a direct-deposit change requires `bank_routing_number`, `bank_account_number`, and `bank_account_type`; incomplete payloads fail with `ERR_VALIDATION`. Two business gates apply at submission: the subject employee must be `ACTIVE` — submitting while `ON_LEAVE` or `TERMINATED` fails with `ERR_EMPLOYEE_INACTIVE` — and an employee may hold only one pending request per change type, so a second submission of the same type while one is `PENDING_VERIFICATION` or `PENDING_APPROVAL` fails with `ERR_DUPLICATE_DATA_CHANGE_PENDING`. The server stamps `submitted_at` from the logical clock.

Whether fraud verification is required is decided at creation. A direct-deposit change always requires it. An address change requires it only when the employee has any fraud verification in `FAILED` or `LOCKED` status created within the trailing thirty days, both ends of that window inclusive; otherwise the request needs no verification. When verification is required, the request opens with `approval_status` at `PENDING_VERIFICATION` and `fraud_status` at `PENDING`, and the server mints exactly one fraud verification for it: a server-generated six-digit `challenge_code`, an `attempts` counter starting at zero, a `status` of `PENDING`, and the verification `method` — `SECURITY_CODE`, where the employee supplies the challenge code, or `MANAGER_CONFIRMATION`, where the manager of record confirms — which the server chooses as `MANAGER_CONFIRMATION` when the subject employee has a manager of record and as `SECURITY_CODE` otherwise. When verification is not required, `fraud_status` is `NOT_REQUIRED` and the request opens directly in `PENDING_APPROVAL`. Either way, creation flips the employee's `has_pending_dcr` to true and bumps the employee's `version`. The request's fraud-verification listing exposes at most one record, and the `challenge_code` is readable there by every role authorized for that listing — the owning employee, an `HRDataSteward`, and an `HRServicesAdmin`.

Verification is attempted by supplying the `method` and, for the code path, an `evidence_code`. Under `SECURITY_CODE` the caller must be the owning employee and the `evidence_code` must equal the minted `challenge_code`. Under `MANAGER_CONFIRMATION` the caller — acting in the `Employee` role — must be the subject employee's manager of record, meaning the caller's `X-User-ID` equals that employee's `manager_id`; anyone else is rejected with `ERR_FORBIDDEN_ROLE`. Two further rejections come ahead of the evidence comparison: a verify call against a request whose fraud dimension is `NOT_REQUIRED` fails with `ERR_DCR_INVALID_STATE`, and a call naming a `method` other than the one issued fails with `ERR_VALIDATION`. A wrong code rejects the attempt with `ERR_FRAUD_EVIDENCE_MISMATCH` and records it: `attempts` increments and the verification's `status` becomes `FAILED`, with the request's `fraud_status` following along. A third failed attempt locks everything: the verification and the request's `fraud_status` both move to `LOCKED`, the request's `approval_status` is driven to `REJECTED` with its `reject_reason` set to `FRAUD_VERIFICATION_LOCKED`, and the employee's `has_pending_dcr` is recomputed. Any verify call against an already-locked verification fails with `ERR_FRAUD_VERIFICATION_LOCKED`, raised at state-check priority ahead of the generic `ERR_DCR_INVALID_STATE` — so a locked request reports its lock, not a bare state error. A successful verification — from `PENDING` or `FAILED`, never from `LOCKED` — sets the verification's `status` to `VERIFIED`, records `verified_by_user_id` (the employee for the code path, the manager for the confirmation path) and `verified_at`, and moves the request's `approval_status` from `PENDING_VERIFICATION` to `PENDING_APPROVAL` with `fraud_status` at `VERIFIED`.

Approval is the compliance moment: it moves a request from `PENDING_VERIFICATION` or `PENDING_APPROVAL` to `APPLIED`, it is performed by an `HRDataSteward`, and it is gated by four checks. The fraud gate comes first: `fraud_status` must be `VERIFIED` or `NOT_REQUIRED`, and approving while verification is still `PENDING` or has `FAILED` fails with `ERR_FRAUD_VERIFICATION_REQUIRED` — a business-safety rejection, not a state error. The subject employee must be `ACTIVE`, otherwise `ERR_EMPLOYEE_INACTIVE`. The steward may not decide their own request — a caller whose `X-User-ID` equals the request's `employee_id` fails with `ERR_SELF_APPROVAL_FORBIDDEN`. And the steward may not approve a request whose verification they personally satisfied — a caller equal to the verification's `verified_by_user_id` fails with `ERR_VERIFIER_CANNOT_APPROVE`.

An approved request applies atomically. The `new_values` are written onto the employee's address or bank block, the employee's `version` increments and `updated_at` refreshes, and the server appends one audit log entry per changed employee field — each naming the `field_changed`, the string-serialized `old_value` (null when the field was previously unset), the `new_value`, the approving steward as `changed_by_user_id`, the originating request as `dcr_id`, and a `change_source` of `DCR_APPLIED`, the only origin this version of the system writes. Applying one request invalidates its siblings: every other data change request of the same employee still in `PENDING_VERIFICATION` or `PENDING_APPROVAL` moves to `CANCELLED`, because a profile mutation invalidates any verification already in flight. The request records `decided_by_user_id`, `decided_at`, and `applied_at`; the employee's `has_pending_dcr` is recomputed — false once no pending requests remain — and the request's `version` increments. The approval machine also documents a return edge from `PENDING_APPROVAL` back to `PENDING_VERIFICATION`, reserved for a future approve-time safety re-check; no public operation takes it in this version, since approval always requires the fraud dimension settled.

Rejection and cancellation are the quieter exits. A steward rejects a `PENDING_APPROVAL` request by supplying a `reason`, stored as the request's `reject_reason`, with `decided_by_user_id` and `decided_at` stamped; the self-decision ban applies here too, as `ERR_SELF_APPROVAL_FORBIDDEN`. The owning employee may cancel their own request while it is `PENDING_VERIFICATION` or `PENDING_APPROVAL`; termination of the employee (§3.1) and application of a sibling request cancel pending requests as system cascades. All three exits recompute `has_pending_dcr`. The request's terminal states are `APPLIED`, `REJECTED`, and `CANCELLED`, and the fraud dimension settles permanently at `NOT_REQUIRED`, `VERIFIED`, or `LOCKED`. Requests are listed with the `employee_id`, `approval_status`, and `change_type` filters — employees see only their own — and any state-incompatible action fails with `ERR_DCR_INVALID_STATE`.

The audit trail is the compliance artifact of the whole pipeline. An employee's own audit log — readable by the employee, stewards, and admins — lists entries newest first, ordered by `created_at` descending, the second exception to the default sort. A global audit listing, restricted to `HRDataSteward` and `HRServicesAdmin`, supports the `employee_id`, `dcr_id`, and `change_source` filters. Audit entries are immutable records carrying only `id` and `created_at` alongside the change payload described above.

### 3.8. Satisfaction Surveys and Agent Coaching

A ticket's first resolution issues exactly one survey, and only the first resolution ever does — a later reopen-and-resolve cycle creates none. The survey is bound to its `ticket_id`, addressed to the requester as `employee_id`, and attributed to whichever agent held the ticket at resolution time as `agent_id` — null if the ticket was unassigned. It opens `ISSUED` with `issued_at` set to the resolution instant and `expires_at` exactly seven days later; `score`, `comment`, and `submitted_at` stay null until the employee answers. `SUBMITTED` and `EXPIRED` are the survey's terminal states.

Submitting moves `ISSUED` to `SUBMITTED`. Only the addressed employee may submit; the `score` must be an integer from 1 to 5 inclusive, anything else failing with `ERR_VALIDATION`, and a free-text `comment` is optional. Two distinct rejections guard the calendar and the state. Lazy expiry means a survey whose `expires_at` has passed fails submission with `ERR_SURVEY_EXPIRED` even if its stored status still reads `ISSUED`; separately, submitting a survey that is already `SUBMITTED`, or one the clock sweep has already moved to `EXPIRED` — the sweep flips any `ISSUED` survey whose expiry is strictly in the past — fails the state check with `ERR_SURVEY_INVALID_STATE`. A successful submission stamps `submitted_at` from the logical clock. Surveys are listed with the `employee_id`, `ticket_id`, `agent_id`, and `status` filters, with employees force-scoped to their own.

Each submission recomputes the attributed agent's rolling satisfaction over the trailing thirty days, both ends inclusive, counting only `SUBMITTED` surveys — issued and expired ones never enter. The recipe is pinned step for step. A survey's age is the whole number of days since submission: the elapsed seconds divided by 86,400, rounded down. Its weight is one-half raised to the power of the age divided by fourteen, rounded half-up to six decimal places. Each weighted term — the score times the weight — is rounded half-up to two decimal places first; only then are the terms summed, the sum divided by the sum of the weights, and the quotient rounded half-up to two decimal places to form the `recency_weighted_mean`. The rounding order is part of the contract: scores of 1, 1, and 2 at ages 0, 0, and 12 days yield 1.21 under the pinned order, where summing the unrounded products and rounding once would yield 1.22. A `simple_mean` — the sum of the scores divided by their count, rounded half-up to two decimals — is computed alongside: scores of 5, 4, and 2 at ages 0, 7, and 28 days give a simple mean of 3.67 against a recency-weighted mean of 4.26. The weighted mean is what lands on the agent as `rolling_csat`, and it stays null until the agent has at least one submitted survey in the window.

The same recomputation drives coaching. An agent's `coaching_hold` is set true when the window holds at least three submitted surveys and the recency-weighted mean falls below 3.00; it is cleared when a later recomputation brings the mean back to the threshold or above. The moment the hold flips from false to true, the agent's open workload is released: every ticket currently assigned to the agent in `TRIAGED`, `IN_PROGRESS`, or `ESCALATED` has its `assigned_agent_id` cleared and its `workflow_status` returned to `TRIAGED`, with a `COACHING_RELEASE` event appended per ticket — a depth-three cascade running from the survey, through the agent's recomputed standing, into the ticket queue. A `COACHING_RELEASE` event is not clock-driven, so its `actor_user_id` is the employee whose survey submission triggered the cascade.

### 3.9. Seasonal Staffing Windows and Shift Planning

Open enrollment and similar surges are planned as staffing windows. A `WorkforcePlanner` creates one for a `team_id` with a `name`, an inclusive `window_start` and `window_end` (the end must not precede the start, otherwise `ERR_INVALID_TIME_RANGE`), the `required_t1_hours` and `required_t2_hours` the window must staff (each zero or more), and an optional `sla_multiplier` — defaulting to 1.0 and never below 1.0 — which stretches the base SLA minutes of tickets created in the team's categories while the window is `ACTIVE`, exactly as §3.4 describes. Windows of the same team may not overlap: because the bounds are inclusive, even two windows merely touching at an endpoint conflict, and a conflicting create is rejected with `ERR_WINDOW_OVERLAP`. The overlap test considers only windows still `PLANNED` or `ACTIVE`; `COMPLETED` and `CANCELLED` windows never conflict. This closed-interval rule is what guarantees at most one `ACTIVE` window per team at any instant.

A window's `status` rides the logical clock. It is born `PLANNED` — or immediately `ACTIVE` when the creation instant already falls inside the window — moves `PLANNED` to `ACTIVE` when the clock reaches `window_start`, and `ACTIVE` to `COMPLETED` once the clock passes `window_end`. Activation requires the new logical time to fall inside the window's inclusive bounds, so a clock jump that lands beyond `window_end` while the window is still `PLANNED` leaves it `PLANNED`, and only `ACTIVE` windows ever complete. The planner may cancel a `PLANNED` or `ACTIVE` window, moving it to `CANCELLED`: its shifts remain on record, but the window stops applying its `sla_multiplier`. `COMPLETED` and `CANCELLED` are terminal, and actions against a finished window — such as cancelling a `COMPLETED` one — fail with `ERR_WINDOW_INVALID_STATE`.

Inside a window, the planner schedules agent shifts, each naming an `agent_id`, the `staffing_window_id`, and a half-open span from `shift_start` to `shift_end`. The window must still be `PLANNED` or `ACTIVE` — scheduling into a completed or cancelled window fails with `ERR_WINDOW_INVALID_STATE`. The span must lie inside the window: a `shift_start` before `window_start` or a `shift_end` after `window_end` fails with `ERR_SHIFT_OUTSIDE_WINDOW`, and an end that does not fall strictly after the start fails with `ERR_INVALID_TIME_RANGE`. One agent cannot be in two places at once, but the overlap test is half-open: a new shift strictly overlapping another `SCHEDULED` shift of the same agent is rejected with `ERR_SHIFT_OVERLAP`, while back-to-back shifts that merely touch are allowed. A shift opens `SCHEDULED`; the planner may cancel it, and cancelling one that is not `SCHEDULED` fails with `ERR_SHIFT_INVALID_STATE`. Cancelled shifts drop out of both coverage accounting and the overlap check. The shift list supports the `agent_id`, `staffing_window_id`, and `status` filters.

Coverage is recomputed whenever a window is read and after every shift creation or cancellation. For each tier, the covered hours are the sum — over the window's `SCHEDULED` shifts worked by agents of that tier — of the overlap in minutes between the half-open shift and the window's inclusive bounds, divided by sixty; shifts are clipped to the window, and a zero or negative clip contributes nothing. The results are exposed as `covered_t1_hours` and `covered_t2_hours`, each rounded half-up to two decimal places. Each tier's coverage ratio is its covered hours divided by its required hours, with a tier requiring zero hours contributing a ratio of exactly 1.0. The window's `coverage_posture` is gated by the weaker tier: `UNDER_STAFFED` when the smaller ratio is below 0.90, `ADEQUATE` when it is at least 0.90 and at most 1.10, and `SURPLUS` beyond 1.10 — so a window that requires nothing on either tier reads as `ADEQUATE`. The window list can be filtered by `team_id` and `status`.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; reads and all state-changing actions on an existing resource return `200 OK`. Request and response payloads for every operation are specified by the workflow narratives in §3 — the table below fixes only the HTTP contract and the authorized roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/hr-helpdesk/employees` | Create an employee | HRServicesAdmin |
| GET | `/hr-helpdesk/employees` | List employees with filters | HRServicesAdmin, HRDataSteward, HelpDeskAgent, SpecialistAgent, SensitiveCaseManager, WorkforcePlanner, KnowledgeManager |
| GET | `/hr-helpdesk/employees/{id}` | Read one employee (Employee role: self only) | Employee, HRServicesAdmin, HRDataSteward, HelpDeskAgent, SpecialistAgent, SensitiveCaseManager |
| POST | `/hr-helpdesk/employees/{id}/status` | Transition employee lifecycle status; terminating cascades pending data change requests to cancelled | HRServicesAdmin |
| GET | `/hr-helpdesk/employees/{id}/audit-log` | Audit trail of profile changes for the employee, newest first | Employee, HRServicesAdmin, HRDataSteward |
| POST | `/hr-helpdesk/teams` | Create a team | HRServicesAdmin |
| GET | `/hr-helpdesk/teams` | List teams | HRServicesAdmin, WorkforcePlanner, HelpDeskAgent, SpecialistAgent, SensitiveCaseManager |
| GET | `/hr-helpdesk/teams/{id}` | Read one team | HRServicesAdmin, WorkforcePlanner, HelpDeskAgent, SpecialistAgent, SensitiveCaseManager |
| POST | `/hr-helpdesk/agents` | Create an agent | HRServicesAdmin |
| GET | `/hr-helpdesk/agents` | List agents with filters | HRServicesAdmin, WorkforcePlanner, HelpDeskAgent, SpecialistAgent, SensitiveCaseManager |
| GET | `/hr-helpdesk/agents/{id}` | Read one agent, including computed load and satisfaction fields | HRServicesAdmin, WorkforcePlanner, HelpDeskAgent, SpecialistAgent, SensitiveCaseManager |
| POST | `/hr-helpdesk/ticket-categories` | Create a ticket category | HRServicesAdmin |
| GET | `/hr-helpdesk/ticket-categories` | List categories | Employee, HRServicesAdmin, HRDataSteward, HelpDeskAgent, SpecialistAgent, SensitiveCaseManager, KnowledgeManager, WorkforcePlanner |
| GET | `/hr-helpdesk/ticket-categories/{id}` | Read one category | Employee, HRServicesAdmin, HRDataSteward, HelpDeskAgent, SpecialistAgent, SensitiveCaseManager, KnowledgeManager, WorkforcePlanner |
| POST | `/hr-helpdesk/sla-policies` | Create an SLA policy row for a category-and-priority pair | HRServicesAdmin |
| GET | `/hr-helpdesk/sla-policies` | List SLA policy rows | HRServicesAdmin, WorkforcePlanner, HelpDeskAgent, SpecialistAgent, SensitiveCaseManager |
| GET | `/hr-helpdesk/ticket-categories/{id}/sla-policies` | List the policy rows of one category | HRServicesAdmin, WorkforcePlanner, HelpDeskAgent, SpecialistAgent, SensitiveCaseManager |
| POST | `/hr-helpdesk/kb-articles` | Author an article draft, optionally as a revision of a published article | KnowledgeManager, HelpDeskAgent, SpecialistAgent |
| GET | `/hr-helpdesk/kb-articles` | Search and list articles; employees see published only | Employee, KnowledgeManager, HRServicesAdmin, HelpDeskAgent, SpecialistAgent, SensitiveCaseManager |
| GET | `/hr-helpdesk/kb-articles/{id}` | Read one article | Employee, KnowledgeManager, HRServicesAdmin, HelpDeskAgent, SpecialistAgent, SensitiveCaseManager |
| POST | `/hr-helpdesk/kb-articles/{id}/submit-review` | Move a draft into review | KnowledgeManager, HelpDeskAgent, SpecialistAgent |
| POST | `/hr-helpdesk/kb-articles/{id}/publish` | Publish a reviewed article; supersedes the prior chain head atomically | KnowledgeManager |
| POST | `/hr-helpdesk/kb-articles/{id}/return-draft` | Return an in-review article to draft for rework | KnowledgeManager |
| POST | `/hr-helpdesk/kb-articles/{id}/archive` | Archive a published article | KnowledgeManager |
| POST | `/hr-helpdesk/article-views` | Record a self-service article view | Employee |
| GET | `/hr-helpdesk/article-views` | List article views with filters | HRServicesAdmin, KnowledgeManager, HelpDeskAgent, SpecialistAgent, SensitiveCaseManager |
| GET | `/hr-helpdesk/article-views/{id}` | Read one article view (owner employee or staff) | Employee, HRServicesAdmin, KnowledgeManager, HelpDeskAgent, SpecialistAgent, SensitiveCaseManager |
| POST | `/hr-helpdesk/tickets` | Intake a ticket: computes SLA deadlines, links a recent article view, auto-assigns a cleared agent for sensitive categories | Employee |
| GET | `/hr-helpdesk/tickets` | List tickets with filters; employees see only their own | Employee, HelpDeskAgent, SpecialistAgent, SensitiveCaseManager, HRServicesAdmin |
| GET | `/hr-helpdesk/tickets/{id}` | Read one ticket; sensitive content is masked for non-cleared readers | Employee, HelpDeskAgent, SpecialistAgent, SensitiveCaseManager, HRServicesAdmin |
| POST | `/hr-helpdesk/tickets/{id}/triage` | Triage a new ticket, optionally overriding priority | HelpDeskAgent, SensitiveCaseManager |
| POST | `/hr-helpdesk/tickets/{id}/assign` | Assign or reassign an agent (optimistic-concurrency checked) | HelpDeskAgent, SpecialistAgent, SensitiveCaseManager, HRServicesAdmin |
| POST | `/hr-helpdesk/tickets/{id}/respond` | Post an agent response; stamps the first-response time | HelpDeskAgent, SpecialistAgent, SensitiveCaseManager |
| POST | `/hr-helpdesk/tickets/{id}/request-info` | Ask the employee for more information | HelpDeskAgent, SpecialistAgent, SensitiveCaseManager |
| POST | `/hr-helpdesk/tickets/{id}/provide-info` | Employee supplies the requested information | Employee |
| POST | `/hr-helpdesk/tickets/{id}/escalate` | Escalate a tier-1 ticket to the category's specialist team | HelpDeskAgent |
| POST | `/hr-helpdesk/tickets/{id}/resolve` | Resolve the ticket; issues the survey on first resolution | HelpDeskAgent, SpecialistAgent, SensitiveCaseManager |
| POST | `/hr-helpdesk/tickets/{id}/reopen` | Reopen a resolved ticket within the reopen window | Employee |
| POST | `/hr-helpdesk/tickets/{id}/close` | Close a resolved ticket | Employee |
| POST | `/hr-helpdesk/tickets/{id}/cancel` | Cancel a new or triaged ticket | Employee |
| GET | `/hr-helpdesk/tickets/{id}/events` | Read the ticket's event log, chronological | Employee, HelpDeskAgent, SpecialistAgent, SensitiveCaseManager, HRServicesAdmin |
| POST | `/hr-helpdesk/data-change-requests` | Submit a profile data change (optimistic-concurrency checked) | Employee |
| GET | `/hr-helpdesk/data-change-requests` | List data change requests; employees see only their own | Employee, HRDataSteward, HRServicesAdmin |
| GET | `/hr-helpdesk/data-change-requests/{id}` | Read one data change request | Employee, HRDataSteward, HRServicesAdmin |
| GET | `/hr-helpdesk/data-change-requests/{id}/fraud-verifications` | Read the request's fraud verification record | Employee, HRDataSteward, HRServicesAdmin |
| POST | `/hr-helpdesk/data-change-requests/{id}/verify` | Attempt fraud verification by code or manager confirmation | Employee |
| POST | `/hr-helpdesk/data-change-requests/{id}/approve` | Approve and apply a verified data change request | HRDataSteward |
| POST | `/hr-helpdesk/data-change-requests/{id}/reject` | Reject a data change request | HRDataSteward |
| POST | `/hr-helpdesk/data-change-requests/{id}/cancel` | Cancel a pending data change request | Employee |
| GET | `/hr-helpdesk/surveys` | List surveys; employees see only their own | Employee, HelpDeskAgent, SpecialistAgent, SensitiveCaseManager, HRServicesAdmin |
| GET | `/hr-helpdesk/surveys/{id}` | Read one survey | Employee, HelpDeskAgent, SpecialistAgent, SensitiveCaseManager, HRServicesAdmin |
| POST | `/hr-helpdesk/surveys/{id}/submit` | Submit a survey score and optional comment | Employee |
| POST | `/hr-helpdesk/staffing-windows` | Create a seasonal staffing window | WorkforcePlanner |
| GET | `/hr-helpdesk/staffing-windows` | List staffing windows | WorkforcePlanner, HRServicesAdmin, HelpDeskAgent, SpecialistAgent, SensitiveCaseManager |
| GET | `/hr-helpdesk/staffing-windows/{id}` | Read one window including computed coverage | WorkforcePlanner, HRServicesAdmin, HelpDeskAgent, SpecialistAgent, SensitiveCaseManager |
| POST | `/hr-helpdesk/staffing-windows/{id}/cancel` | Cancel a planned or active window | WorkforcePlanner |
| POST | `/hr-helpdesk/agent-shifts` | Schedule an agent shift inside a window | WorkforcePlanner |
| GET | `/hr-helpdesk/agent-shifts` | List shifts | WorkforcePlanner, HRServicesAdmin |
| GET | `/hr-helpdesk/agent-shifts/{id}` | Read one shift | WorkforcePlanner, HRServicesAdmin |
| POST | `/hr-helpdesk/agent-shifts/{id}/cancel` | Cancel a scheduled shift | WorkforcePlanner |
| GET | `/hr-helpdesk/audit-log-entries` | Global audit trail of employee data changes | HRServicesAdmin, HRDataSteward |
| GET | `/hr-helpdesk/audit-log-entries/{id}` | Read one audit log entry | HRServicesAdmin, HRDataSteward |
| GET | `/hr-helpdesk/metrics/deflection` | Knowledge-base deflection rate for a category over the trailing thirty days | HRServicesAdmin, KnowledgeManager, WorkforcePlanner |
| GET | `/hr-helpdesk/metrics/sla-attainment` | SLA attainment for a category over tickets that reached resolution | HRServicesAdmin, WorkforcePlanner, HelpDeskAgent, SpecialistAgent, SensitiveCaseManager |
| GET | `/hr-helpdesk/metrics/csat` | Agent satisfaction means over the trailing thirty days | HRServicesAdmin, WorkforcePlanner, HelpDeskAgent, SpecialistAgent, SensitiveCaseManager |
| POST | `/hr-helpdesk/_clock/set_current_utc` | Set the logical clock and run the time-driven sweeps | HRServicesAdmin |

## 5. Error Code Catalogue

The catalogue fixes the identifier and HTTP status of every rejection; the conditions that trigger each error are specified in §2 and §3 alongside the rules they guard. Two identifiers appear only at the platform edge: reading a single audit log entry whose id does not resolve fails with `ERR_AUDIT_ENTRY_NOT_FOUND`, and a request to an undeclared path or with an unsupported method is rejected with `ERR_NOT_FOUND`.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_ENUM` | 400 Bad Request |
| `ERR_EMPLOYEE_NOT_FOUND` | 404 Not Found |
| `ERR_AGENT_NOT_FOUND` | 404 Not Found |
| `ERR_TEAM_NOT_FOUND` | 404 Not Found |
| `ERR_CATEGORY_NOT_FOUND` | 404 Not Found |
| `ERR_SLA_POLICY_NOT_FOUND` | 404 Not Found |
| `ERR_ARTICLE_NOT_FOUND` | 404 Not Found |
| `ERR_TICKET_NOT_FOUND` | 404 Not Found |
| `ERR_DCR_NOT_FOUND` | 404 Not Found |
| `ERR_SURVEY_NOT_FOUND` | 404 Not Found |
| `ERR_WINDOW_NOT_FOUND` | 404 Not Found |
| `ERR_SHIFT_NOT_FOUND` | 404 Not Found |
| `ERR_AUDIT_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_TICKET_INVALID_STATE` | 409 Conflict |
| `ERR_DCR_INVALID_STATE` | 409 Conflict |
| `ERR_ARTICLE_INVALID_STATE` | 409 Conflict |
| `ERR_SURVEY_INVALID_STATE` | 409 Conflict |
| `ERR_WINDOW_INVALID_STATE` | 409 Conflict |
| `ERR_SHIFT_INVALID_STATE` | 409 Conflict |
| `ERR_EMPLOYEE_INVALID_STATE` | 409 Conflict |
| `ERR_CONFIDENTIALITY_CLEARANCE_REQUIRED` | 403 Forbidden |
| `ERR_FRAUD_VERIFICATION_REQUIRED` | 409 Conflict |
| `ERR_FRAUD_VERIFICATION_LOCKED` | 409 Conflict |
| `ERR_FRAUD_EVIDENCE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_EMPLOYEE_INACTIVE` | 422 Unprocessable Entity |
| `ERR_SELF_APPROVAL_FORBIDDEN` | 403 Forbidden |
| `ERR_VERIFIER_CANNOT_APPROVE` | 403 Forbidden |
| `ERR_AUTHOR_CANNOT_PUBLISH` | 403 Forbidden |
| `ERR_AGENT_AT_CAPACITY` | 409 Conflict |
| `ERR_AGENT_TIER_INSUFFICIENT` | 409 Conflict |
| `ERR_NO_ELIGIBLE_SPECIALIST` | 422 Unprocessable Entity |
| `ERR_SHIFT_OVERLAP` | 409 Conflict |
| `ERR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_SLA_POLICY_DUPLICATE` | 409 Conflict |
| `ERR_DUPLICATE_DATA_CHANGE_PENDING` | 409 Conflict |
| `ERR_DUPLICATE_EMPLOYEE_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_CATEGORY_CODE` | 409 Conflict |
| `ERR_REOPEN_WINDOW_PASSED` | 409 Conflict |
| `ERR_SURVEY_EXPIRED` | 409 Conflict |
| `ERR_INVALID_TIME_RANGE` | 422 Unprocessable Entity |
| `ERR_SHIFT_OUTSIDE_WINDOW` | 422 Unprocessable Entity |
| `ERR_RESOLUTION_ARTICLE_NOT_PUBLISHED` | 422 Unprocessable Entity |
| `ERR_CATEGORY_INACTIVE` | 422 Unprocessable Entity |
| `ERR_STALE_TICKET_VERSION` | 412 Precondition Failed |
| `ERR_STALE_EMPLOYEE_VERSION` | 412 Precondition Failed |
