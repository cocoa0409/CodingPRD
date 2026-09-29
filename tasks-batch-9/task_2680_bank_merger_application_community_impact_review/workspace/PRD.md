# Bank Merger Application & Community Impact Review API — Product Requirements Document

## 1. Introduction

Bank merger applications fail far more often on process than on economics. A corporate development team can negotiate a defensible price, and the transaction can still stall because a deposit-market concentration screen was never run for one overlapping county, because a substantive community protest was answered with an acknowledgement rather than a response, because a branch-closing notice was mailed eighty-nine days before the office stopped taking deposits, or because the closing was attempted three days before the statutory waiting period had elapsed. Every one of those failures is a bookkeeping failure over a fixed set of rules, and every one of them is expensive: waiting periods restart, comment windows reopen, and the acquirer's next filing is read against a worse record.

This document specifies the service that carries a bank merger from transaction structuring through post-closing commitment monitoring. It is a single system of record shared by two adversarial constituencies and one referee. The acquirer's team — the **Filer** — builds the transaction, files it, designates the branches it is prepared to give up, negotiates a community benefits package, answers the public record, closes the deal and reports quarterly against its commitments. Members of the public, community organizations, trade groups and government bodies — **PublicCommenter** actors — put comments and protests on the record and may petition for a public hearing. The regulator's staff maintain the institutional and banking-market record, run the concentration screens, manage the comment window, recommend an outcome, decide, and monitor the conditions afterwards, split across three distinct regulator roles so that the analyst who recommends is never the official who decides.

The service is deliberately deterministic. Concentration is computed from branch-level deposits by a pinned six-step procedure rather than estimated; pro forma capital is computed twice, once on the basis filed with the regulator and once on the board's downside case, and only the regulatory basis gates a filing; waiting periods are arithmetic over the transaction's structure, its hearing history and its protest record; commitment fulfilment is measured against frozen pro-rata targets under whichever of two measurement bases the plan itself elected. All temporal reasoning reads a server-held logical UTC clock rather than wall-clock time, so a reviewer can drive a 180-day consummation window in a single session. All collections are mounted at the service root — there is no shared URL prefix — and every relationship between records is expressed as an explicit reference carried in a request body rather than by nesting.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to every endpoint, including reads, must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the capacity in which that principal is acting. If either header is absent, or if `X-User-Role` is not one of the five declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If both headers are present and well-formed but the acting role is not among the roles authorized for the endpoint being called, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403). The authentication check always precedes the authorization check; no other validation runs before either.

The five roles are `Filer`, `PublicCommenter`, `CaseAnalyst`, `ApprovingOfficial` and `ComplianceMonitor`, spelled exactly as shown.

A `Filer` is the acquiring institution's corporate development team. When `X-User-Role` is `Filer`, `X-User-ID` is the `id` of the acting `Institution`; ownership checks on any resource that references an `Institution` compare the resource's foreign-key field to `X-User-ID`. Concretely, a `Filer` may act on a merger application only when `X-User-ID` equals that application's `acquirer_id`, and the same comparison reaches every record that hangs off the application — its pro forma capital schedules, its branch designations, its community benefits plans and line items, its comment responses, its consummation, its systems conversion plan and its performance reports. A `Filer` whose `X-User-ID` does not match the application's `acquirer_id` is rejected with `ERR_NOT_APPLICATION_FILER` (HTTP 403).

When `X-User-Role` is `PublicCommenter`, `X-User-ID` is an opaque commenter identifier not tied to any persisted entity. The server records it — as `commenter_user_id` on a public comment and as `requester_user_id` on a hearing request — but never compares it to any entity's `id`. Ownership among commenters is therefore commenter-to-commenter: a `PublicCommenter` may withdraw only a hearing request whose `requester_user_id` equals the acting `X-User-ID`, and any other commenter attempting the withdrawal is rejected with `ERR_NOT_REQUEST_OWNER` (HTTP 403).

When `X-User-Role` is `CaseAnalyst`, `X-User-ID` is an opaque regulator-staff identifier not tied to any persisted entity. The server may record it — it is stored as `recommended_by_user_id` on the application when the staff recommendation is entered — but it is never compared to any entity's `id`. When `X-User-Role` is `ApprovingOfficial`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server records it as `decided_by_user_id` on a hearing-request ruling and as `decided_by_user_id` on an approval decision. When `X-User-Role` is `ComplianceMonitor`, `X-User-ID` is again an opaque operator identifier not tied to any persisted entity, recorded as `reviewed_by_user_id` on a performance report and as `satisfied_by_user_id` on an approval condition.

Although the three regulator identities are opaque, one comparison between them is load-bearing. Segregation of duties requires that the `ApprovingOfficial` who issues the decision be a different person from the `CaseAnalyst` who recorded the staff recommendation: the acting `X-User-ID` at decision time must differ from the application's stored `recommended_by_user_id`. When the two are equal the decision is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). This is the only place in the service where two opaque identifiers are compared to each other.

Read access is broad. Every role may read institutions, deposit markets, branches, merger applications, competitive analyses, comment periods, public comments, hearing requests, community benefits plans, commitment line items, approval decisions, approval conditions and performance reports. Two read surfaces are narrower: pro forma capital schedules and systems conversion plans are visible to `CaseAnalyst`, `ApprovingOfficial`, `ComplianceMonitor` and `Filer` but not to `PublicCommenter`, and the consolidated clearance summary of an application is likewise closed to `PublicCommenter`.

Writes are tightly partitioned. Only a `CaseAnalyst` registers institutions, creates deposit markets, adds branches, runs competitive analyses, opens and closes comment periods, accepts a filing for substantive review, returns a filing for amendment, records the staff recommendation, and drives the logical clock. Only a `Filer` opens a merger application, submits it, designates and rescinds branch designations, proposes and executes community benefits plans and their line items, responds to public comments, consummates, registers and discloses and completes a systems conversion, and files performance reports. Only a `PublicCommenter` files public comments, requests hearings and withdraws their own hearing requests. Only an `ApprovingOfficial` rules on hearing requests, issues approval decisions and attaches approval conditions. Only a `ComplianceMonitor` records condition satisfaction, reviews performance reports and reopens them. Two write surfaces are shared: amending an application's structure or examiner scores is open to both `Filer` and `CaseAnalyst`, and building a pro forma capital schedule is likewise open to both.

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

Every list endpoint accepts two optional query-string parameters. `limit` controls page size: its default is 10, its minimum accepted value is 1 and its maximum accepted value is 100. `offset` controls how many records are skipped before the page begins: its default is 0 and its minimum accepted value is 0. A `limit` below 1 or above 100, or a negative `offset`, is a malformed request.

List results are ordered by `created_at` ascending. Where two records share a `created_at` instant, the ordering remains stable across repeated calls.

For list responses the `meta` object carries four pagination fields alongside the request identifier and timestamp: `limit` and `offset` echoing the values in force for the page, `total_count` giving the number of records matching the filter before pagination is applied, and `has_more` reporting whether any matching record falls after the returned page. Single-resource responses omit all four.

Filters on list endpoints are additive: supplying several narrows the result set to records matching all of them. The institution list accepts `charter_type`, `primary_regulator` and `status`; the deposit-market list accepts `market_type`; the branch list accepts `institution_id`, `market_id`, `designation_application_id` and `status`; the merger-application list accepts `acquirer_id`, `target_id` and `filing_status`; the pro forma schedule list accepts `application_id`, `basis` and `status`; the competitive-analysis list accepts `application_id`, `market_id` and `screen_result`; the comment-period list accepts `application_id` and `status`; the public-comment list accepts `period_id`, `stance` and `status`; the hearing-request list accepts `application_id`, `comment_id` and `status`; the benefits-plan list accepts `application_id` and `status`; the line-item list accepts `plan_id` and `category`; the approval-decision list accepts `application_id` and `status`; the approval-condition list accepts `decision_id`, `timing`, `status` and `condition_type`; the systems-conversion-plan list accepts `application_id` and `status`; and the performance-report list accepts `plan_id` and `status`.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted record carries a server-minted `id`. Identifiers are UUIDs with no type prefix — a branch id and an application id are indistinguishable by shape, so callers must not attempt to infer a record's type from its identifier. Clients never supply an `id`.

Every record also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits, set once at creation and never modified. Every entity in this service also carries `updated_at`, an ISO 8601 UTC timestamp in the same format, refreshed on every mutation of the record, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation. There are no exceptions in this domain: institutions, deposit markets, branches, merger applications, pro forma capital schedules, competitive analyses, comment periods, public comments, hearing requests, community benefits plans, commitment line items, approval decisions, approval conditions, systems conversion plans and performance reports all expose `id`, `created_at`, `updated_at` and `version`.

Time is not read from the host. The service holds a logical UTC clock that a `CaseAnalyst` may set to an arbitrary instant by supplying `now`; the response echoes `now`. Before any such call the clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time. Every temporal evaluation in this specification — the instant a comment is received, the instant a hearing ruling is recorded, the instant a decision is issued, the opening and deadline of a consummation window, the lead-day arithmetic for branch-closing notices and customer conversion disclosures, and the earliest instant staff may recommend — reads that logical clock.

Because relationships are expressed by reference rather than by nesting, most write endpoints carry the parent's identifier in the request body. Where an identifier does appear in a URL path, it is resolved before the body is examined, and where a path carries more than one identifier they are resolved left to right, the leftmost first. A path identifier that does not resolve produces the not-found error for that record type — `ERR_INSTITUTION_NOT_FOUND`, `ERR_MARKET_NOT_FOUND`, `ERR_BRANCH_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_SCHEDULE_NOT_FOUND`, `ERR_ANALYSIS_NOT_FOUND`, `ERR_COMMENT_PERIOD_NOT_FOUND`, `ERR_COMMENT_NOT_FOUND`, `ERR_HEARING_REQUEST_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_LINE_ITEM_NOT_FOUND`, `ERR_DECISION_NOT_FOUND`, `ERR_CONDITION_NOT_FOUND`, `ERR_CONVERSION_PLAN_NOT_FOUND` or `ERR_REPORT_NOT_FOUND` — all at HTTP 404. A foreign key carried in a request body that does not resolve produces the same family of not-found errors at HTTP 404: an unresolvable institution reference yields `ERR_INSTITUTION_NOT_FOUND`, an unresolvable market reference `ERR_MARKET_NOT_FOUND`, an unresolvable application reference `ERR_APPLICATION_NOT_FOUND`, an unresolvable comment-period reference `ERR_COMMENT_PERIOD_NOT_FOUND`, an unresolvable comment reference `ERR_COMMENT_NOT_FOUND`, an unresolvable benefits-plan reference `ERR_PLAN_NOT_FOUND` and an unresolvable decision reference `ERR_DECISION_NOT_FOUND`.

### 2.5. Rejection Precedence

Several rules can be violated by a single request. The order in which the service evaluates them is normative, because the caller must be able to predict which error surfaces. Checks run in the following sequence, and the first violated check ends the request:

1. Header presence and role validity — `ERR_UNAUTHENTICATED`.
2. Endpoint role authorization — `ERR_ROLE_NOT_PERMITTED`.
3. Existence of every identifier in the request path, resolved left to right — the appropriate not-found error.
4. Request-body shape: the body parses; every required input field is present; every enum-typed value is a declared member of its enumeration; every USD amount is a non-negative integer; every examiner score is an integer from 0 through 100 inclusive; `term_years` is from 1 through 10 inclusive; `duration_days` is from 7 through 90 inclusive; and every supplied timestamp is a valid UTC instant. Any failure is `ERR_INVALID_REQUEST` (HTTP 400).
5. Filer ownership — the acting `X-User-ID` equals the target application's `acquirer_id` — `ERR_NOT_APPLICATION_FILER`.
6. Hearing-request ownership on withdrawal — `ERR_NOT_REQUEST_OWNER`.
7. Segregation of duties on issuing a decision — `ERR_SEGREGATION_OF_DUTIES`.
8. Existence of every foreign key carried in the request body — the appropriate not-found error.
9. Optimistic concurrency: `expected_application_version` equals the referenced application's current `version` — `ERR_STALE_APPLICATION_VERSION` (HTTP 412).
10. Own-resource state: the target record is in a state from which the requested transition is declared — one of `ERR_INVALID_APPLICATION_STATE`, `ERR_COMMENT_PERIOD_NOT_OPEN`, `ERR_INVALID_HEARING_REQUEST_STATE`, `ERR_INVALID_PLAN_STATE`, `ERR_INVALID_DECISION_STATE`, `ERR_INVALID_CONDITION_STATE`, `ERR_INVALID_CONVERSION_PLAN_STATE`, `ERR_INVALID_REPORT_STATE` or `ERR_INVALID_BRANCH_STATE`, all at HTTP 409.
11. Cross-entity state: both institutions are `ACTIVE` at submission, the decision is `CONSUMMATED` before a systems conversion, every comment period is `CLOSED` before consummation, and no hearing request citing a comment of a period is `PENDING` when that period closes — one of `ERR_INSTITUTION_NOT_ACTIVE`, `ERR_HEARING_REQUEST_PENDING`, `ERR_COMMENT_PERIOD_NOT_OPEN` or `ERR_INVALID_DECISION_STATE`, all at HTTP 409.
12. The acquirer's Community Reinvestment Act record is adequate at submission — `ERR_CRA_RATING_INSUFFICIENT`.
13. The application's management rating is not `UNSATISFACTORY` — `ERR_MANAGEMENT_ASSESSMENT_UNSATISFACTORY`.
14. Pre-consummation and systems-conversion conditions are satisfied — `ERR_CONDITION_NOT_SATISFIED`.
15. The application's competitive posture is not `BLOCKED` — `ERR_COMPETITIVE_POSTURE_BLOCKED`.
16. A comment arrives before the grace tail has expired — `ERR_COMMENT_WINDOW_CLOSED`.
17. The cited comment's period is `OPEN` or `EXTENDED` when a hearing is requested or ruled upon — `ERR_COMMENT_PERIOD_NOT_OPEN`.
18. A new comment period does not overlap an existing period of the application — `ERR_COMMENT_PERIOD_OVERLAP`.
19. A closure designation carries sufficient customer notice lead time — `ERR_CLOSURE_NOTICE_LEAD_INSUFFICIENT`.
20. No buffered branch-closure window intersects the systems-conversion window — `ERR_CONVERSION_BLACKOUT_CONFLICT`.
21. The customer conversion disclosure carries sufficient lead time — `ERR_DISCLOSURE_LEAD_INSUFFICIENT`.
22. The waiting period has elapsed — `ERR_WAITING_PERIOD_NOT_ELAPSED`.
23. The consummation deadline has not passed — `ERR_CONSUMMATION_WINDOW_LAPSED`.
24. Both parties overlap in the market being analyzed — `ERR_NO_MARKET_OVERLAP`.
25. A hearing petition cites a live substantive protest — `ERR_NO_SUBSTANTIVE_PROTEST`.
26. Every overlapping market has been analyzed before a recommendation — `ERR_MARKET_ANALYSIS_MISSING`.
27. A current regulatory-basis pro forma schedule exists at submission — `ERR_PRO_FORMA_SCHEDULE_MISSING`.
28. An executed community benefits plan exists where one is required — `ERR_BENEFITS_PLAN_NOT_EXECUTED`.
29. An institution's primary regulator agrees with its charter class — `ERR_REGULATOR_CHARTER_MISMATCH`.
30. The acquirer and the target are different institutions — `ERR_SELF_MERGER`.
31. Uniqueness constraints — `ERR_DUPLICATE_MARKET_CODE`, `ERR_DUPLICATE_ANALYSIS`, `ERR_DUPLICATE_CONVERSION_PLAN` or `ERR_DUPLICATE_REPORT_PERIOD`, all at HTTP 409.
32. A performance report is filed in sequence — `ERR_REPORT_PERIOD_OUT_OF_SEQUENCE`.
33. Both institutions report the capital denominators a pro forma schedule needs — `ERR_CAPITAL_DATA_MISSING`.
34. A closure designation carries its notice dates and a disclosure carries the mail channel — `ERR_CLOSURE_NOTICE_REQUIRED`.
35. A full response carries response text — `ERR_RESPONSE_BODY_REQUIRED`.
36. The current regulatory-basis schedule shows the combined institution well capitalized at submission — `ERR_PRO_FORMA_CAPITAL_INSUFFICIENT`.
37. An executed plan carries at least one funded commitment — `ERR_EMPTY_BENEFITS_PLAN`.

Two consequences of this ordering deserve emphasis. First, because the stale-version check sits at step 9 — ahead of every state and business check — a client working from an outdated view of an application is told so before any richer diagnosis is attempted. Second, because own-resource state (step 10) precedes every business-safety and temporal check, a consummation attempt against a decision that is no longer `ISSUED` reports the state error rather than a waiting-period or condition error.

### 2.6. Optimistic Concurrency on the Application Record

Two write operations hang off the merger application in a way that is legitimate on its own terms but destructive if the client's picture of the application is out of date, and both are therefore guarded by optimistic concurrency control against the application record.

Creating a pro forma capital schedule requires `expected_application_version` as a non-optional field of the request body, carrying the client's last observed `version` of the referenced `MergerApplication`. If that value does not equal the application's current `version`, the create is rejected with `ERR_STALE_APPLICATION_VERSION` at HTTP 412. Nothing about the schedule itself is blocked — a new schedule for a given basis legitimately supersedes the prior current schedule of that basis — so the stale version is the only signal available that the client's view of which schedule is current, and therefore of which capital figures the submission gate will read, has moved on.

Proposing a community benefits plan likewise requires `expected_application_version` as a non-optional field carrying the client's last observed `version` of the referenced `MergerApplication`, and a value that does not equal the application's current `version` is rejected with `ERR_STALE_APPLICATION_VERSION` at HTTP 412. Again no state precondition blocks the write — a new proposed plan legitimately supersedes the application's prior proposed plan — so the stale version is the only signal that the filer is negotiating against a commitment baseline that has since been replaced.

No other endpoint accepts a version field. Amending an application, submitting it, designating a branch, executing a plan, adding a line item, responding to a comment, issuing a decision, consummating, converting systems and filing or reviewing a report all take no `expected_application_version` and are never rejected with `ERR_STALE_APPLICATION_VERSION`.

### 2.7. Measurement Precision and Rounding

Money in this service is always whole US dollars, stored and returned as integers. Wherever a calculation divides dollars, the quotient is floored to a whole dollar unless this document says otherwise, and wherever an intermediate dollar amount arises inside the pro forma capital arithmetic it is truncated toward zero to a whole integer before being used further.

Percentages and ratios are reported to two decimal places using round-half-up: a value whose third decimal digit is 5 or greater rounds the second decimal digit upward. This governs `management_composite_score`, `pro_forma_cet1_ratio_pct`, `pro_forma_tier1_leverage_pct`, `fulfillment_pct` and `alternate_fulfillment_pct`.

Concentration arithmetic uses a deeper intermediate precision. Each participant's market share, expressed as a percentage, is rounded half-up to four decimal places before it is squared, and the sum of the squared shares is rounded half-up to a whole integer to give a Herfindahl-Hirschman Index value. Every index field in this service — `hhi_current`, `hhi_pre_merger`, `hhi_post_unmitigated`, `hhi_post_mitigated` — is therefore an integer, and `hhi_delta_unmitigated`, being the difference of two such integers, is an integer as well.

Day counts are whole UTC days and are floored. Where a lead time is measured between two instants, the number of whole days between them is taken and any partial day is discarded.

### 2.8. The Includable Branch Set

Deposit-market concentration is built bottom-up from individual branch balances, and one definition governs which balances count. A branch is **includable** when its `status` is `OPEN`, `DESIGNATED_FOR_DIVESTITURE` or `DESIGNATED_FOR_CLOSURE`. A branch whose `status` is `DIVESTED` or `CLOSED` is excluded from every aggregate.

The consequence is deliberate and easy to get wrong: designating a branch for divestiture or for closure does **not** remove its deposits from the market's deposit base. Only an actual divestiture or an actual closure does. Designation is a promise, not a disposal, and keeping designated deposits in the base is what allows the mitigation arithmetic to be evaluated against a stable denominator rather than against a base that shifts every time the filer changes its mind.

Four aggregates are recomputed from the includable set whenever a branch is created, whenever a branch changes `status`, and whenever a branch is reassigned from one owner to another at consummation. A deposit market's `total_deposits_usd` is the sum of `deposits_usd` over its includable branches. A market's `participant_count` is the number of distinct `institution_id` values among the owners of its includable branches. An institution's `total_deposits_usd` is the sum of `deposits_usd` over its own includable branches, and its `branch_count` is the number of those branches. A market's `hhi_current` is then computed by taking, for each institution present in the market, that institution's in-market includable deposits divided by the market's `total_deposits_usd`, multiplied by 100 and rounded half-up to four decimal places; squaring each of those share percentages; summing the squares; and rounding the sum half-up to a whole integer. A market with no includable branches carries `total_deposits_usd` of 0, `participant_count` of 0 and `hhi_current` of 0.

### 2.9. Cascade Discipline and Compensating Actions

Several operations in this service touch more than one record, and in each case the secondary effects are part of the operation's contract rather than incidental bookkeeping. Where a cascade is specified, the whole chain either happens or the request is rejected before any of it happens; a caller never observes a partially applied cascade.

Three cascade chains recur and are worth naming up front. Granting a hearing petition changes the petition, extends the cited comment window, and pushes back the earliest instant at which staff may recommend. Designating a branch for divestiture changes the branch, recomputes the competitive analysis for that branch's market, re-rolls the application's overall competitive posture from all of its analyses, and can satisfy an open divestiture condition on the application's decision. Reviewing a performance report changes the report, moves the plan's credit ledger and compliance counters, can breach a post-closing community benefits condition, and can escalate the application's post-closing monitoring posture.

Two of these chains have exact compensating actions. Rescinding a branch designation reverses the designation cascade: the analysis is recomputed, the posture is re-rolled, and a divestiture condition that the designation had satisfied returns to `OPEN` if the posture stops clearing. Reopening a reviewed performance report reverses the review cascade dollar for dollar: exactly the credits applied at review are removed, the deficiency counters are stepped back, and a condition that this review had breached returns to `OPEN`. The ledger identity that makes the reversal verifiable is that a plan's `credited_to_date_usd` plus its `remaining_commitment_usd` always equals its `total_committed_usd`, before the review and after the reopen alike.

Every mutation, whether requested directly or applied as a cascade, refreshes the mutated record's `updated_at` and increments its `version` by 1. Where this document says an operation increments the application's `version`, that increment happens once per operation regardless of how many of the application's derived fields the operation recomputed.

### 2.10. Two Interval Conventions

This service reasons about two kinds of date range, and they do not share a convention. Getting them confused is the single most common source of off-by-one disputes in merger casework, so both are stated here explicitly.

A **public comment window** occupies a half-open interval: it includes its opening instant and excludes its closing instant. A window opens at `opens_at` and closes at `closes_at`, and an instant exactly equal to `closes_at` is outside the window. Two windows of the same application overlap when the first opens strictly before the second closes and the second opens strictly before the first closes; windows that merely touch — one beginning at exactly the instant another ends — do not overlap and are both legal. A new window may therefore open at exactly the closing instant of a prior window.

A **branch-closure window** occupies a closed interval and is additionally buffered on both sides. The window runs from 15 days before the branch-closing notice was mailed through 15 days after the office is planned to stop taking deposits, and both endpoints are inside the window. A systems-conversion window is likewise closed at both ends, running from `conversion_start_date` through `conversion_end_date` inclusive. These two closed intervals conflict when the buffered closure window's start is at or before the conversion window's end **and** the conversion window's start is at or before the buffered closure window's end — so two windows that merely touch after buffering are already in conflict, which is the opposite of the comment-window rule.

## 3. Business Logic & Workflows

### 3.1. Building the Institutional and Banking-Market Record

Nothing can be filed until the regulator's case file knows who the parties are and where they compete. A `CaseAnalyst` registers each bank or holding company with its chartered `legal_name`, between 1 and 160 characters and not blank, and its `charter_type`, which is one of `NATIONAL`, `STATE_MEMBER`, `STATE_NONMEMBER` or `SAVINGS`. The `primary_regulator` accompanying it is one of `OCC`, `FRB` or `FDIC`, and it is not free to disagree with the charter class: a `NATIONAL` charter requires `OCC`, a `STATE_MEMBER` charter requires `FRB`, and both a `STATE_NONMEMBER` charter and a `SAVINGS` charter require `FDIC`. A mismatched pair is refused with `ERR_REGULATOR_CHARTER_MISMATCH`.

Registration also captures the balance-sheet figures the pro forma arithmetic will consume later, each an optional whole-dollar integer of at least 0 that defaults to 0 when omitted: `cet1_capital_usd` for common equity tier 1 capital, `tier1_capital_usd` for tier 1 capital, `total_capital_usd` for total regulatory capital, `risk_weighted_assets_usd` for risk-weighted assets, `average_total_assets_usd` for the average total consolidated assets that serve as the leverage denominator, and `total_loans_usd` for gross loans held for investment — the base to which the downside credit mark is applied. The Community Reinvestment Act record is carried as `latest_cra_rating`, one of `OUTSTANDING`, `SATISFACTORY`, `NEEDS_TO_IMPROVE` or `SUBSTANTIAL_NONCOMPLIANCE`, defaulting to `SATISFACTORY` when the caller omits it, alongside `cra_exam_closed_at`, the close date of the examination that produced that rating, which defaults to null. A newly registered institution is `ACTIVE`, with `total_deposits_usd` of 0 and `branch_count` of 0; `status` is one of `ACTIVE` or `MERGED_OUT` and only the service sets it.

Banking markets are registered next. Each carries a `market_code` — an MSA or rural county identifier between 2 and 32 characters that must be unique across all deposit markets, a duplicate being refused with `ERR_DUPLICATE_MARKET_CODE` — a human-readable `market_name`, and a `market_type` of either `MSA` or `RURAL_COUNTY`. The market type is not cosmetic: it selects which post-merger concentration ceiling the screen applies. A market is created with `total_deposits_usd` of 0, `participant_count` of 0 and `hhi_current` of 0.

Branches are the atomic unit of everything that follows. Adding one names its owner through `institution_id`, its market through `market_id`, its `branch_name`, and the `deposits_usd` booked at that office, which must be strictly greater than 0. Its `service_type` is either `FULL_SERVICE`, the default, marking an office with deposit-taking capability, or `LIMITED_SERVICE`, marking a drive-up or kiosk. A new branch is `OPEN`, and its `designation_application_id`, `notice_sent_at`, `planned_closure_date` and `notice_lead_days` are all null. Creating it immediately recomputes the market's `total_deposits_usd`, `participant_count` and `hhi_current` and the owning institution's `total_deposits_usd` and `branch_count`, and every competitive analysis touching that market is recomputed as well — a new competitor branch in an already-analyzed market changes the screen for that market retroactively.

### 3.2. Structuring the Transaction and Scoring Management

A `Filer` opens the case by describing the deal. The `acquirer_id` names the surviving institution and, by the ownership rule of §2.1, the only filer permitted to act on the application thereafter; the `target_id` names the institution being acquired and must be a different institution, since a filing where the two are equal is refused with `ERR_SELF_MERGER`. The `structure` is one of `STATUTORY_MERGER`, `PURCHASE_AND_ASSUMPTION` or `HOLDCO_ACQUISITION` and later selects the base statutory waiting period. The `consideration_type` is one of `ALL_CASH`, `ALL_STOCK` or `MIXED`, and `total_consideration_usd` records the aggregate deal price in whole dollars, strictly greater than 0.

Four examiner scores travel with the application, each an optional integer from 0 through 100 inclusive that defaults to 0: `officer_experience_score` for proposed senior officer depth and experience, `risk_management_score` for the pro forma risk-management framework, `compliance_history_score` for the acquirer's consumer-compliance and Bank Secrecy Act history, and `integration_readiness_score` for the integration plan covering staffing, systems and project governance. From these the service derives `management_composite_score` as a weighted blend, and the weighting order is normative because it is observable in the second decimal place. Each score is multiplied by its own weight — 0.35 for officer experience, 0.30 for risk management, 0.175 for compliance history and 0.175 for integration readiness — and **each weighted product is rounded half-up to two decimal places before any addition happens**. The four rounded products are then added and the sum is itself rounded half-up to two decimal places to give `management_composite_score`. Summing the unrounded products and rounding once at the end produces a different answer in ordinary cases and is not what this service does.

The composite is then banded into `management_rating`: a composite of 70.00 or more is `SATISFACTORY`, a composite of at least 55.00 but below 70.00 is `CONDITIONAL`, and anything below 55.00 is `UNSATISFACTORY`. A freshly opened application therefore starts with `management_composite_score` of 0.00 and `management_rating` of `UNSATISFACTORY` unless the filer supplied scores.

A new application starts in `filing_status` `DRAFT` on one axis and `public_review_status` `NOT_OPEN` on the other, with `competitive_posture` `NOT_ANALYZED`, `substantive_protest_count` and `unresolved_protest_count` at 0, `amendment_round` at 0, `post_closing_monitoring_status` `NOT_APPLICABLE`, and `earliest_decision_at`, `recommendation` and `recommended_by_user_id` all null.

Amending an undecided application is open to both the `Filer` who owns it and to a `CaseAnalyst`, and any subset of `structure`, `consideration_type`, `total_consideration_usd`, `officer_experience_score`, `risk_management_score`, `compliance_history_score` and `integration_readiness_score` may be supplied. Whenever any examiner score changes the composite and the rating are recomputed by the same per-product rounding procedure, and the amendment increments the application's `version` by 1.

The two status axes on an application are genuinely independent. `filing_status` moves through `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `RETURNED_FOR_AMENDMENT`, `RECOMMENDED`, `DECIDED`, `CONSUMMATED` and `DENIED`, with `CONSUMMATED` and `DENIED` terminal. `public_review_status` moves through `NOT_OPEN`, `OPEN_FOR_COMMENT`, `PROTEST_PENDING`, `HEARING_PENDING`, `HEARING_GRANTED`, `COMMENT_CLOSED` and `CLEARED`, with `CLEARED` terminal. An application can sit in `UNDER_REVIEW` while its community review walks from `OPEN_FOR_COMMENT` to `PROTEST_PENDING` to `HEARING_GRANTED` and back, and neither axis constrains the other except where this document says so explicitly.

### 3.3. Pro Forma Capital on Two Bases

Before a filing can be made, the combined institution's opening capital position must be modelled. A schedule names its application through `application_id`, carries `expected_application_version` as described in §2.6, and declares its `basis`: either `REGULATORY_ADJUSTED`, the figures filed with the regulator, or `INTERNAL_STRESS`, the board's downside case. Both a `Filer` and a `CaseAnalyst` may build one. Six purchase-accounting adjustments travel with it, each a whole-dollar integer of at least 0: `goodwill_created_usd` for the goodwill recognised on the opening balance sheet, `core_deposit_intangible_usd` for the core deposit intangible recognised at close, `aoci_markdown_usd` for the unrealised loss on available-for-sale securities, `deferred_tax_asset_usd` for the deferred tax asset the transaction creates, `transaction_costs_usd` for one-time merger expenses charged to capital, and `cash_consideration_usd` for the cash paid at close, which reduces the leverage denominator.

The schedule reads the acquirer's and the target's reported capital fields, and it refuses to run on incomplete data: if either institution reports `risk_weighted_assets_usd` of zero or `average_total_assets_usd` of zero, the build is refused with `ERR_CAPITAL_DATA_MISSING`. Superseded schedules are never re-read.

Both bases begin from the same intangibles figure — the goodwill created plus the core deposit intangible — and both end the same way: `pro_forma_cet1_ratio_pct` is the common-equity numerator divided by the risk-weighted-asset denominator, multiplied by 100 and rounded half-up to two decimal places, and `pro_forma_tier1_leverage_pct` is the tier 1 numerator divided by the average-total-asset denominator, multiplied by 100 and rounded half-up to two decimal places. Every intermediate dollar amount is truncated toward zero to a whole integer before it is used.

On the **`REGULATORY_ADJUSTED`** basis the arithmetic runs as follows. Add the acquirer's `cet1_capital_usd` to the target's, then subtract the intangibles figure; call the result the pre-deduction common equity. The deferred tax asset receives an allowance equal to 10 percent of that pre-deduction common equity, truncated toward zero to a whole dollar; the excess deferred tax asset is the amount by which `deferred_tax_asset_usd` exceeds that allowance, or zero when it does not exceed it. The common-equity numerator is the pre-deduction common equity less `transaction_costs_usd` less that excess deferred tax asset. The tier 1 numerator is the acquirer's `tier1_capital_usd` plus the target's, less the intangibles figure, less `transaction_costs_usd`, less the same excess deferred tax asset. The risk-weighted-asset denominator is the acquirer's `risk_weighted_assets_usd` plus the target's, less the intangibles figure. The average-total-asset denominator is the acquirer's `average_total_assets_usd` plus the target's, less the intangibles figure, less `cash_consideration_usd`. On this basis `aoci_markdown_usd` is disclosed on the schedule but is not deducted from anything.

On the **`INTERNAL_STRESS`** basis the arithmetic is harsher in four specific ways. A credit mark is taken first: 2.5 percent of the target's `total_loans_usd`, truncated toward zero to a whole dollar. The common-equity numerator is the acquirer's `cet1_capital_usd` plus the target's, less the intangibles figure, less `aoci_markdown_usd`, less the **entire** `deferred_tax_asset_usd` with no allowance at all, less `transaction_costs_usd`, less that credit mark. The tier 1 numerator is the acquirer's `tier1_capital_usd` plus the target's, less the intangibles figure, less `aoci_markdown_usd`, less the entire `deferred_tax_asset_usd`, less `transaction_costs_usd`, less the credit mark. The risk-weighted-asset denominator is the acquirer's `risk_weighted_assets_usd` plus the target's, less the intangibles figure, **plus** an inflation add-on of 5 percent of the target's `risk_weighted_assets_usd`, truncated toward zero to a whole dollar. The average-total-asset denominator is computed exactly as on the regulatory basis: the two institutions' `average_total_assets_usd` summed, less the intangibles figure, less `cash_consideration_usd`.

The resulting pair of ratios is banded into `capital_adequacy_flag`. When the common-equity ratio is at least 7.00 percent and the leverage ratio is at least 5.00 percent, the flag is `WELL_CAPITALIZED`. Otherwise, when the common-equity ratio is at least 4.50 percent and the leverage ratio is at least 4.00 percent, the flag is `ADEQUATELY_CAPITALIZED`. In any other case the flag is `UNDERCAPITALIZED`. Both conditions in a band must hold; a common-equity ratio of 9 percent with a leverage ratio of 4.2 percent is `ADEQUATELY_CAPITALIZED`, not `WELL_CAPITALIZED`.

Each schedule carries a `status` of `CURRENT` or `SUPERSEDED`, and at most one schedule per application and basis is `CURRENT`. Building a new schedule on a basis moves the prior current schedule of that same basis to `SUPERSEDED`, and increments the application's `version` by 1. Only the current `REGULATORY_ADJUSTED` schedule gates a filing; an `INTERNAL_STRESS` schedule is informational and never blocks anything.

### 3.4. Filing, Acceptance and the Amendment Cycle

Filing takes the application from `DRAFT` to `SUBMITTED`, and it is the tightest gate in the service. Six conditions must hold, and each has its own rejection. The acting `Filer` must be the acquirer, or the filing is refused with `ERR_NOT_APPLICATION_FILER`. Both the acquirer and the target must have `status` `ACTIVE`, since an institution that has already been merged away can be neither party to a new filing; either being `MERGED_OUT` yields `ERR_INSTITUTION_NOT_ACTIVE`. The acquirer's `latest_cra_rating` must be `OUTSTANDING` or `SATISFACTORY`, and a rating of `NEEDS_TO_IMPROVE` or `SUBSTANTIAL_NONCOMPLIANCE` yields `ERR_CRA_RATING_INSUFFICIENT`. The application's `management_rating` must be `SATISFACTORY` or `CONDITIONAL`; a rating of `UNSATISFACTORY` yields `ERR_MANAGEMENT_ASSESSMENT_UNSATISFACTORY`. A pro forma capital schedule with `basis` `REGULATORY_ADJUSTED` and `status` `CURRENT` must exist for the application, and its absence yields `ERR_PRO_FORMA_SCHEDULE_MISSING`. Finally that schedule's `capital_adequacy_flag` must be `WELL_CAPITALIZED`, and any weaker flag yields `ERR_PRO_FORMA_CAPITAL_INSUFFICIENT`. A successful filing sets `filing_status` to `SUBMITTED` and increments the application's `version` by 1.

Acceptance for substantive review is the `CaseAnalyst`'s act and drives `SUBMITTED → UNDER_REVIEW`. It is refused if any public comment period of the application already has a window containing the current clock instant, since the service will not open a second window on top of a live one. Acceptance does four things at once. It sets `filing_status` to `UNDER_REVIEW`. It creates a public comment period for the application, opening at the current clock instant with a `duration_days` of 30 and `status` `OPEN`. It moves the community-review axis `NOT_OPEN → OPEN_FOR_COMMENT`. And it sets `earliest_decision_at` to that period's `closes_at` plus a further 15 days of post-comment review time. The application's `version` increments by 1.

Returning a filing to the filer is also the `CaseAnalyst`'s act and is available from two states. From `SUBMITTED → RETURNED_FOR_AMENDMENT` the only requirement is a `reason` that is present and non-blank; the transition sets `filing_status` and increments `version` by 1. From `UNDER_REVIEW → RETURNED_FOR_AMENDMENT` the same non-blank `reason` is required **and** no hearing request on the application may still be `PENDING`, a live petition yielding `ERR_HEARING_REQUEST_PENDING`. This second edge additionally closes the community record: every comment period of the application whose `status` is `OPEN` or `EXTENDED` moves to `CLOSED`, and the application's `public_review_status` becomes `COMMENT_CLOSED`. Its `version` increments by 1.

Re-filing after amendment is the cycle that closes the loop: `RETURNED_FOR_AMENDMENT → SUBMITTED` runs exactly the same six gate conditions as the first filing, with the same six rejections. It differs in one respect — it increments `amendment_round` by 1 in addition to setting `filing_status` to `SUBMITTED` and incrementing `version` by 1. `DRAFT` is never re-entered once an application has been filed.

### 3.5. Deposit-Market Concentration and the Divestiture Requirement

A concentration screen is run per market. A `CaseAnalyst` names the `application_id` and the `market_id`, and the request is refused with `ERR_NO_MARKET_OVERLAP` unless both the acquirer and the target each hold at least one includable branch in that market. At most one analysis may exist for a given application and market pair, a second attempt being refused with `ERR_DUPLICATE_ANALYSIS`.

The screen runs as a pinned six-step procedure. Steps 1 through 3 look only at current ownership and the unmitigated merger; steps 4 through 6 layer mitigation on top and never revisit the first three. This ordering is what resolves what would otherwise be circular — the required divestiture depends on the mitigated concentration, which depends on the divestiture.

**Step 1 — pre-merger concentration.** Take the market's `total_deposits_usd` over its includable branches as the denominator. For each institution present in the market, divide its in-market includable deposits by that denominator, multiply by 100, and round half-up to four decimal places to obtain its share percentage. Square each share percentage, sum the squares, and round the sum half-up to a whole integer. That value is `hhi_pre_merger`, and every institution is counted separately in it, including the acquirer and the target.

**Step 2 — post-merger concentration, unmitigated.** `combined_market_deposits_usd` is the acquirer's in-market includable deposits plus the target's, taking no account of any designation. Recompute the share set with every other participant's share unchanged and one combined share for the merged firm, obtained by dividing `combined_market_deposits_usd` by the same market denominator, multiplying by 100 and rounding half-up to four decimal places. Square, sum and round half-up to a whole integer to obtain `hhi_post_unmitigated`. Then `hhi_delta_unmitigated` is `hhi_post_unmitigated` less `hhi_pre_merger`.

**Step 3 — the screen, evaluated in this exact order.** The post-merger ceiling depends on the market class: 1800 for a market whose `market_type` is `MSA`, and 2200 for a market whose `market_type` is `RURAL_COUNTY`. First, if `hhi_post_unmitigated` is strictly below that ceiling, `screen_result` is `PASS`. Otherwise, if `hhi_delta_unmitigated` is at most 200, `screen_result` is `PASS` — a delta of exactly 200 passes on this branch. Otherwise, if `hhi_post_unmitigated` is at least 2500 **and** `hhi_delta_unmitigated` is strictly greater than 400, `screen_result` is `PRESUMPTIVE_VIOLATION`. In every remaining case `screen_result` is `MITIGATION_REQUIRED`. Note the two boundaries carefully: a market can pass on either the absolute-level branch or the delta branch, and a delta of exactly 400 at a post-merger level of 2500 or more is `MITIGATION_REQUIRED`, not `PRESUMPTIVE_VIOLATION`.

**Step 4 — the divestiture requirement.** When `screen_result` is `PASS`, `required_divestiture_deposits_usd` is 0. Otherwise the service searches for the smallest whole multiple of one million dollars that would clear the screen, testing one million, then two million, then three million and so on, never exceeding `combined_market_deposits_usd`. For each candidate amount, the merged firm's deposits after divestiture are `combined_market_deposits_usd` less that candidate; the trial share set consists of the other participants' shares unchanged, plus a share for the merged firm computed from its reduced deposits, plus a share for one single hypothetical new entrant computed from the candidate amount itself — each of those shares divided by the same unchanged market denominator, multiplied by 100 and rounded half-up to four decimal places. Squaring, summing and rounding half-up to a whole integer gives the trial index, and the trial delta is that index less `hhi_pre_merger`. The first candidate whose trial index is strictly below the market's ceiling, or whose trial delta is at most 200, becomes `required_divestiture_deposits_usd`. If no candidate up to and including `combined_market_deposits_usd` satisfies either test, `required_divestiture_deposits_usd` is `combined_market_deposits_usd`. Because divested deposits are attributed to exactly one hypothetical new entrant rather than vanishing, they keep contributing to the index at a smaller share.

**Step 5 — what the filer has actually promised.** `designated_divestiture_deposits_usd` is the sum of `deposits_usd` over the branches in this market whose `status` is `DESIGNATED_FOR_DIVESTITURE` and whose `designation_application_id` equals this application. Branches designated for closure never count here. The merged firm's deposits after designation are `combined_market_deposits_usd` less `designated_divestiture_deposits_usd`, and `hhi_post_mitigated` is computed from the other participants' unchanged shares, plus a share for the merged firm's reduced deposits, plus — only when the designated amount is greater than zero — one share for the designated deposits as a single new entrant; each share taken over the same market denominator, multiplied by 100, rounded half-up to four decimal places, squared, summed and rounded half-up to a whole integer.

**Step 6 — the mitigation verdict.** `mitigation_satisfied` is true when two things both hold: `designated_divestiture_deposits_usd` is at least `required_divestiture_deposits_usd`, **and** either `hhi_post_mitigated` is strictly below the market's ceiling or `hhi_post_mitigated` less `hhi_pre_merger` is at most 200. If either half fails, `mitigation_satisfied` is false, and a freshly created analysis with no designations carries `designated_divestiture_deposits_usd` of 0 and `mitigation_satisfied` false unless the screen itself passed.

Every analysis of an application then rolls up into the application's `competitive_posture`, and the worst market decides. When the application has no analyses at all the posture is `NOT_ANALYZED`. Otherwise, if any analysis has `screen_result` `PRESUMPTIVE_VIOLATION` and `mitigation_satisfied` false, the posture is `BLOCKED`. Otherwise, if any analysis has `screen_result` `MITIGATION_REQUIRED` and `mitigation_satisfied` false, the posture is `MITIGATION_REQUIRED`. Otherwise, if any analysis has a `screen_result` other than `PASS`, the posture is `CLEARED_WITH_DIVESTITURE` — a market that failed its screen but is fully mitigated still unblocks the case while recording that divestiture was needed. Only when every analysis passed outright is the posture `CLEARED`. The severity ordering, worst first, is `BLOCKED`, then `MITIGATION_REQUIRED`, then `CLEARED_WITH_DIVESTITURE`, then `CLEARED`. The roll-up is re-evaluated on every creation or recomputation of an analysis and on every branch designation or rescission.

Once the transaction is consummated, competitive analyses are frozen: they are not recomputed thereafter, however the market's branches subsequently move.

### 3.6. Branch Designations: Divestiture, Closure Notice and the Blackout

Mitigation is expressed by designating individual branches. The acting `Filer` names the `application_id` under which the designation is made and a `designation_type` of either `DIVESTITURE` or `CLOSURE`, and two preconditions are common to both types: the branch's `institution_id` must be either the application's `acquirer_id` or its `target_id`, and the application's `filing_status` must not be `CONSUMMATED` or `DENIED`. A branch that is not `OPEN` cannot be designated, an attempt yielding `ERR_INVALID_BRANCH_STATE`.

A **divestiture designation** drives `OPEN → DESIGNATED_FOR_DIVESTITURE` and stamps `designation_application_id` with the application. It then cascades in three further steps. The competitive analysis for that application and the branch's market recomputes `designated_divestiture_deposits_usd`, `hhi_post_mitigated` and `mitigation_satisfied`. The application's `competitive_posture` is then re-rolled from all of its analyses. And, once that posture is `CLEARED` or `CLEARED_WITH_DIVESTITURE`, every approval condition on the application's decision whose `condition_type` is `DIVESTITURE` and whose `status` is `OPEN` becomes `SATISFIED`, with `satisfied_by_user_id` recorded as the literal string `"system"` and `satisfied_at` stamped from the logical clock. This last link is why a filer can clear a divestiture condition by designating branches rather than by asking the monitor to act.

A **closure designation** drives `OPEN → DESIGNATED_FOR_CLOSURE` and is considerably more demanding, because closing a branch triggers customer-notice obligations. Both `notice_sent_at`, the date the customer branch-closing notice was mailed, and `planned_closure_date`, the date the office stops accepting deposits, must be present; omitting either yields `ERR_CLOSURE_NOTICE_REQUIRED`. From them the service computes `notice_lead_days` as the number of whole UTC days from `notice_sent_at` to `planned_closure_date`, discarding any partial day, and that lead time must be at least 90 days; anything shorter yields `ERR_CLOSURE_NOTICE_LEAD_INSUFFICIENT`. Finally the buffered closure window described in §2.10 must not intersect the application's systems-conversion window, a conflict yielding `ERR_CONVERSION_BLACKOUT_CONFLICT`. The designation records `designation_application_id`, `notice_sent_at`, `planned_closure_date` and `notice_lead_days`, and recomputes the competitive analysis for that market — but closure deposits never count as divestiture mitigation, so `designated_divestiture_deposits_usd` does not move. `notice_lead_days` remains null whenever either notice date is absent.

Rescinding a designation is the compensating action, available while the application's `filing_status` is neither `CONSUMMATED` nor `DENIED`. From `DESIGNATED_FOR_DIVESTITURE → OPEN` it clears `designation_application_id`, recomputes the market's analysis figures — `designated_divestiture_deposits_usd`, `hhi_post_mitigated` and `mitigation_satisfied` — re-rolls the application's `competitive_posture`, and returns to `OPEN` any divestiture condition that had been satisfied by cascade once the posture is no longer `CLEARED` or `CLEARED_WITH_DIVESTITURE`. From `DESIGNATED_FOR_CLOSURE → OPEN` it clears `designation_application_id`, `notice_sent_at`, `planned_closure_date` and `notice_lead_days` and recomputes the market's analysis. Neither rescission edge changes the market's deposit base, because designation never removed the deposits from it in the first place.

Two terminal branch outcomes are reached only by cascade and never by direct request. `DESIGNATED_FOR_DIVESTITURE → DIVESTED` happens when the application whose id sits in `designation_application_id` is consummated. `DESIGNATED_FOR_CLOSURE → CLOSED` happens when that same application's systems conversion completes. In both cases the branch leaves the includable set, so the market's `total_deposits_usd`, `participant_count` and `hhi_current` are all recomputed.

### 3.7. The Public Comment Record

A comment period is either created automatically when a filing is accepted for review, or opened deliberately by a `CaseAnalyst` naming the `application_id`, the `opens_at` instant and an optional `duration_days` that defaults to 30 and, as a stored value, ranges from 1 through 90. A window's `closes_at` is always its `opens_at` plus `duration_days` plus `extended_days_total`, and the interval is half-open on the right as §2.10 describes. A newly created period is `OPEN` with `extension_count` of 0, `extended_days_total` of 0, `comment_count` of 0 and `substantive_protest_count` of 0, and it moves the application's community-review axis `NOT_OPEN → OPEN_FOR_COMMENT`. Creating a period whose interval overlaps any existing period of the same application is refused with `ERR_COMMENT_PERIOD_OVERLAP`; a period that begins exactly where a prior one ended is accepted.

Comments come from `PublicCommenter` actors and name their `period_id`. Each carries a `commenter_name` — the person or organisation going on the record — a `commenter_type` of `INDIVIDUAL`, `COMMUNITY_ORGANIZATION`, `TRADE_GROUP` or `GOVERNMENT`, a `stance` of `SUPPORT`, `OPPOSE` or `PROTEST`, a `body` of between 1 and 4000 characters, and an optional `substantive` flag defaulting to false that is set true when the comment raises a specific, fact-based Community Reinvestment Act or convenience-and-needs objection. The service stamps `received_at` from the logical clock and takes `commenter_user_id` from the acting `X-User-ID`. `response_body` and `responded_at` begin null.

Timeliness has three outcomes, and they are decided by where `received_at` falls. A comment received strictly before the period's `closes_at` is created with `status` `RECEIVED`. A comment received at or after `closes_at` but strictly before `closes_at` plus 3 days is created with `status` `UNTIMELY` — it is stored as a matter of record but never counts toward any protest aggregate and never founds a hearing petition, and it is born in that state rather than transitioning into it. A comment received at or after `closes_at` plus 3 days is refused outright with `ERR_COMMENT_WINDOW_CLOSED`. The grace tail is accepted whether the period's `status` is `OPEN`, `EXTENDED` or already `CLOSED`.

Filing a comment recomputes four counters. The period's `comment_count` is the number of comments on it regardless of `status`. The period's `substantive_protest_count` counts the comments on that period whose `stance` is `PROTEST`, whose `substantive` flag is true, and whose `status` is `RECEIVED`, `ACKNOWLEDGED` or `RESPONDED`. The application's `substantive_protest_count` counts the same population across all of the application's periods. The application's `unresolved_protest_count` narrows that same population further, to comments whose `status` is `RECEIVED` or `ACKNOWLEDGED` — in other words those not yet fully answered. `UNTIMELY` comments are excluded from all three protest counts. When a substantive protest is recorded and the resulting `substantive_protest_count` is at least 1, the application's community-review axis moves `OPEN_FOR_COMMENT → PROTEST_PENDING`.

The filer answers the record with a `disposition` and, where the disposition is a full response, a `response_body`. A `disposition` of `ACKNOWLEDGED` drives `RECEIVED → ACKNOWLEDGED` and stamps `responded_at`, but an acknowledgement does **not** resolve the protest — an `ACKNOWLEDGED` comment still counts as unresolved. A `disposition` of `RESPONDED` drives either `RECEIVED → RESPONDED` or `ACKNOWLEDGED → RESPONDED`, requires a `response_body` that is present and non-blank on pain of `ERR_RESPONSE_BODY_REQUIRED`, and records `response_body` and `responded_at`. Only the acquirer may respond, and the acting `X-User-ID` must equal the application's `acquirer_id`. Each full response recomputes the application's `unresolved_protest_count`. When that count reaches 0 and no hearing request on the application is `PENDING` and the period is still `OPEN` or `EXTENDED`, the application's community-review axis returns `PROTEST_PENDING → OPEN_FOR_COMMENT`.

Closing a period is the `CaseAnalyst`'s act, available from `OPEN → CLOSED` and from `EXTENDED → CLOSED`. It is refused with `ERR_HEARING_REQUEST_PENDING` while any hearing request citing a comment of that period is still `PENDING`. Closing sets the period's `status` to `CLOSED`, sets the application's `earliest_decision_at` to that period's `closes_at` plus 15 days of post-comment review, and — once every period of the application is `CLOSED` — moves the application's community-review axis to `COMMENT_CLOSED`. That axis reaches `COMMENT_CLOSED` from `OPEN_FOR_COMMENT`, from `PROTEST_PENDING` and from `HEARING_GRANTED` alike; each of those three edges carries the same precondition that every period of the application is `CLOSED` after the call, and the same effect on the axis.

### 3.8. Hearing Petitions and the Divergent Grant and Denial Cascades

A `PublicCommenter` may petition for a public hearing, naming the `application_id`, the `comment_id` of the substantive protest the petition is founded on, and a `basis` of between 1 and 2000 characters explaining why a hearing is needed. Two things must hold: the cited comment must itself be a substantive protest and its period's `substantive_protest_count` must be at least 1, failing which the petition is refused with `ERR_NO_SUBSTANTIVE_PROTEST`; and the cited comment's period must have `status` `OPEN` or `EXTENDED`, failing which it is refused with `ERR_COMMENT_PERIOD_NOT_OPEN`. The petition is created with `status` `PENDING`, `requested_at` stamped from the logical clock, `requester_user_id` taken from the acting `X-User-ID`, `extension_days_granted` at 0, and `decided_at`, `decided_by_user_id` and `decision_rationale` null. Its creation moves the application's community-review axis `PROTEST_PENDING → HEARING_PENDING`.

An `ApprovingOfficial` rules on the petition with an `outcome` and a `decision_rationale`. Both rulings require the application's `filing_status` to be `UNDER_REVIEW`, and a petition that is no longer `PENDING` cannot be ruled on at all, an attempt yielding `ERR_INVALID_HEARING_REQUEST_STATE`. The two outcomes then diverge sharply, and the divergence is the point.

An `outcome` of `GRANTED` additionally requires the cited comment's period to have `status` `OPEN` or `EXTENDED`, failing which the ruling is refused with `ERR_COMMENT_PERIOD_NOT_OPEN`. The grant then runs a three-link cascade. First, the petition moves `PENDING → GRANTED` with `decided_at` stamped from the logical clock, `decided_by_user_id` taken from the acting `X-User-ID`, `decision_rationale` recorded, and `extension_days_granted` set to 30. Second — caused by the first link, not by the caller — the cited period moves `OPEN → EXTENDED`: 30 days are added to its `extended_days_total`, its `closes_at` is recomputed as `opens_at` plus `duration_days` plus the new `extended_days_total`, and its `extension_count` increments by 1. Third — caused by the second link — the application's `earliest_decision_at` becomes the extended `closes_at` plus 15 days, and its community-review axis moves `HEARING_PENDING → HEARING_GRANTED`.

An `outcome` of `DENIED` requires `decision_rationale` to be present. The petition moves `PENDING → DENIED` with `decided_at`, `decided_by_user_id` and `decision_rationale` recorded and `extension_days_granted` left at 0. Nothing else moves: the cited period keeps its original `closes_at`, its `extended_days_total` and `extension_count` are untouched, and the application's `earliest_decision_at` is untouched. The community-review axis then falls back, and which way it falls depends on the protest record — `HEARING_PENDING → PROTEST_PENDING` when the application's `unresolved_protest_count` is at least 1, and `HEARING_PENDING → OPEN_FOR_COMMENT` when that count is 0. Both fallback edges additionally require that no other hearing request on the application is still `PENDING`; while another petition is live the axis stays at `HEARING_PENDING`.

The requester may withdraw their own petition instead, and only the requester may: the acting `X-User-ID` must equal the petition's `requester_user_id`, or the withdrawal is refused with `ERR_NOT_REQUEST_OWNER`. Withdrawal drives `PENDING → WITHDRAWN`, leaves `extension_days_granted` at 0, and applies exactly the same axis fallback as a denial — `PROTEST_PENDING` when `unresolved_protest_count` is at least 1 and no other petition is `PENDING`, `OPEN_FOR_COMMENT` when that count is 0 and no other petition is `PENDING`. All three of `GRANTED`, `DENIED` and `WITHDRAWN` are terminal for a petition.

### 3.9. Community Benefits: Proposal, Line Items and Execution

A community benefits package is negotiated on the record. The `Filer` proposes a plan against an `application_id`, supplying `expected_application_version` as §2.6 requires, a `term_years` from 1 through 10 inclusive, and an optional `measurement_basis` of either `CUMULATIVE_TO_DATE`, the default, or `ANNUAL_PRO_RATA`. A new plan is created with `status` `PROPOSED`, every monetary aggregate at 0 — `total_committed_usd`, `annual_target_total_usd`, `quarterly_target_total_usd`, `credited_to_date_usd` and `remaining_commitment_usd` — with `compliance_status` `COMPLIANT`, `consecutive_deficient_periods` at 0 and `filed_report_count` at 0. Creating it moves the application's prior `PROPOSED` plan to `SUPERSEDED` and increments the application's `version` by 1. Only a `PROPOSED` plan is superseded this way; an `EXECUTED` plan blocks the creation of a replacement, and `EXECUTED` and `SUPERSEDED` are both terminal.

Dollars are attached one category at a time. A line item names its `plan_id`, a `category` of `MORTGAGE_LENDING`, `SMALL_BUSINESS_LENDING`, `PHILANTHROPY`, `BRANCH_RETENTION` or `CDFI_INVESTMENT`, and a `committed_usd` strictly greater than 0. At most one line item may exist per plan and category. Adding a line item to a plan that has left `PROPOSED` is refused with `ERR_INVALID_PLAN_STATE`.

Each line item's pro-rata targets follow directly from the plan's term. Its `annual_target_usd` is `committed_usd` divided by the plan's `term_years`, floored to a whole dollar. Its `final_year_target_usd` is `committed_usd` less `annual_target_usd` multiplied by one fewer than `term_years` — so the final year absorbs the entire flooring remainder and the per-item totals reconcile exactly, even though the annual target multiplied by the term may fall short of the commitment. Adding a line item also recomputes three plan aggregates: `total_committed_usd` as the sum of `committed_usd` across the plan's line items, `annual_target_total_usd` as the sum of the individual `annual_target_usd` values — each floored first, then summed, never the other way round — and `quarterly_target_total_usd` as `annual_target_total_usd` divided by the four quarters of a year, floored to a whole dollar. `remaining_commitment_usd` is always `total_committed_usd` less `credited_to_date_usd`, and each line item's `credited_usd` starts at 0 and can never exceed that item's `committed_usd`.

Execution is the filer's commitment and drives `PROPOSED → EXECUTED`. The acting `X-User-ID` must equal the application's `acquirer_id`; the plan must carry at least one commitment line item with a `total_committed_usd` greater than 0, an empty or unfunded plan being refused with `ERR_EMPTY_BENEFITS_PLAN`; and the application's `filing_status` must be `UNDER_REVIEW`, `RECOMMENDED` or `DECIDED`. Execution freezes `total_committed_usd`, `annual_target_total_usd` and `quarterly_target_total_usd` from the line items as they stand at that moment, sets `compliance_status` to `COMPLIANT`, sets `credited_to_date_usd` to 0 and sets `remaining_commitment_usd` to `total_committed_usd`. No further line items may be added afterwards, and the frozen `quarterly_target_total_usd` is the denominator of every fulfilment measurement that follows.

### 3.10. Recommendation, the Decision Order and the Statutory Waiting Period

The staff recommendation drives `UNDER_REVIEW → RECOMMENDED` and is a `CaseAnalyst` act carrying a `recommendation` of `APPROVE`, `APPROVE_WITH_CONDITIONS` or `DENY`. Four preconditions gate it, in addition to the general management-rating and posture checks. The application's `public_review_status` must be `COMMENT_CLOSED`. The current clock instant must be at or after the application's `earliest_decision_at`, which is why a granted hearing pushes the whole case out by 30 days of extra comment window plus the 15 days of post-comment review. No hearing request on the application may still be `PENDING`, a live petition yielding `ERR_HEARING_REQUEST_PENDING`. And a competitive analysis must exist for every deposit market in which both parties hold an includable branch; a single unanalyzed overlap market yields `ERR_MARKET_ANALYSIS_MISSING`. Beyond those, the application's `management_rating` must not be `UNSATISFACTORY`, or the recommendation is refused with `ERR_MANAGEMENT_ASSESSMENT_UNSATISFACTORY`, and its `competitive_posture` must not be `BLOCKED`, or it is refused with `ERR_COMPETITIVE_POSTURE_BLOCKED`.

A successful recommendation sets `filing_status` to `RECOMMENDED`, stores the supplied `recommendation`, stamps `recommended_by_user_id` with the acting `X-User-ID`, and increments the application's `version` by 1. It also closes the community-review axis when the record is clean: `COMMENT_CLOSED → CLEARED` happens exactly when `unresolved_protest_count` is 0, and the axis is left unchanged when any protest remains unresolved.

The `ApprovingOfficial` then issues the order against an `application_id` with a `decision` of `APPROVED`, `CONDITIONALLY_APPROVED` or `DENIED`. The acting `X-User-ID` must differ from the application's `recommended_by_user_id`, and an official who is the recorded recommender is refused with `ERR_SEGREGATION_OF_DUTIES`. At most one order may exist per application; a second attempt is refused with `ERR_DECISION_ALREADY_ISSUED`. An approving order — `APPROVED` or `CONDITIONALLY_APPROVED` — additionally requires the application's `competitive_posture` not to be `BLOCKED`, yielding `ERR_COMPETITIVE_POSTURE_BLOCKED` otherwise; a `DENIED` order carries no posture gate at all and may be issued against a blocked application. Either way the order records `decided_by_user_id` from the acting `X-User-ID` and stamps `decided_at` from the logical clock, and both consummation timestamps are anchored to `decided_at`.

The waiting period is then computed from five inputs read at the instant the order is issued: the application's `structure`, whether any hearing request on it has `status` `GRANTED`, its `unresolved_protest_count`, the largest `hhi_delta_unmitigated` across its analyses, and its `management_rating`. The base period is 30 days when the `structure` is `HOLDCO_ACQUISITION` and 15 days for either bank-level structure. The application is eligible for `expedited_processing` — a boolean stored on the order — when four things hold together: its `unresolved_protest_count` is 0, no hearing request on it has been granted, the largest `hhi_delta_unmitigated` across its analyses is at most 200 (taken as 0 when it has no analyses), and its `management_rating` is exactly `SATISFACTORY`. Adjustments are then applied to the base: 15 days are added when a hearing has been granted, 10 days are added when the `unresolved_protest_count` is greater than 0, and 10 days are subtracted when `expedited_processing` is true. `waiting_period_days` is the larger of the adjusted figure and a floor of 5 days. The additions and the reduction are mutually exclusive in practice, because expedited eligibility itself requires no granted hearing and no unresolved protest, but the 5-day floor still applies to the result. `consummation_window_open_at` is `decided_at` advanced by `waiting_period_days` whole days, and consummation is permitted at that instant inclusive. `consummation_deadline_at` is `decided_at` advanced by 180 whole days, and consummation is permitted through that instant inclusive.

An approving order takes the application `RECOMMENDED → DECIDED`, is created with `status` `ISSUED`, and increments the application's `version` by 1. A `DENIED` order takes the application `RECOMMENDED → DENIED`, is created with `status` `CLOSED`, `waiting_period_days` of 0 and both consummation timestamps null, and unwinds the transaction's footprint: every branch whose `designation_application_id` is this application and whose `status` is `DESIGNATED_FOR_DIVESTITURE` or `DESIGNATED_FOR_CLOSURE` reverts to `OPEN` with `designation_application_id`, `notice_sent_at` and `planned_closure_date` cleared, and each affected market's `hhi_current` is recomputed. It too increments the application's `version` by 1. `consummated_at` begins null on every order.

Conditions are attached to an issued order by the `ApprovingOfficial`, naming the `decision_id`, a `condition_type` of `DIVESTITURE`, `COMMUNITY_BENEFITS`, `CAPITAL_MAINTENANCE`, `BRANCH_RETENTION` or `SYSTEMS_CONVERSION`, a `timing` of either `PRE_CONSUMMATION` or `POST_CLOSING`, a `description` of between 1 and 2000 characters, and an optional `threshold_usd` naming the dollar threshold the condition references, which defaults to null. A condition is created with `status` `OPEN` and with `satisfied_at` and `satisfied_by_user_id` null. Pre-consummation conditions gate the closing; post-closing conditions are monitored afterwards.

A `ComplianceMonitor` records satisfaction, driving `OPEN → SATISFIED`. The order must have `status` `ISSUED` or `CONSUMMATED`. A `DIVESTITURE` condition additionally requires the application's `competitive_posture` to be `CLEARED` or `CLEARED_WITH_DIVESTITURE`. A `COMMUNITY_BENEFITS` condition additionally requires an `EXECUTED` community benefits plan to exist on the application, its absence yielding `ERR_BENEFITS_PLAN_NOT_EXECUTED`. Satisfaction stamps `satisfied_at` from the logical clock and `satisfied_by_user_id` with the acting `X-User-ID`. A condition that is already `SATISFIED` cannot be satisfied again, an attempt yielding `ERR_INVALID_CONDITION_STATE`. No status of a condition is terminal, because a breach is curable.

### 3.11. Consummation, Systems Conversion and Customer Disclosure

Consummation is the `Filer`'s act against the issued order, and it drives both `filing_status` `DECIDED → CONSUMMATED` and the order's `ISSUED → CONSUMMATED`. Six things must hold. The acting `X-User-ID` must equal the application's `acquirer_id`. The order's `status` must be `ISSUED` and its `decision` must be `APPROVED` or `CONDITIONALLY_APPROVED`. Every approval condition on the order whose `timing` is `PRE_CONSUMMATION` must have `status` `SATISFIED`; a condition still `OPEN` or sitting in `BREACHED` yields `ERR_CONDITION_NOT_SATISFIED`. The current clock instant must be at or after `consummation_window_open_at`, an earlier attempt yielding `ERR_WAITING_PERIOD_NOT_ELAPSED`. The current clock instant must be at or before `consummation_deadline_at`. And every public comment period of the application must have `status` `CLOSED`. Additionally, when the order carries a condition whose `condition_type` is `COMMUNITY_BENEFITS`, an `EXECUTED` community benefits plan must exist for the application.

A successful consummation runs a wide cascade. The order's `status` becomes `CONSUMMATED` and its `consummated_at` is stamped from the logical clock. The application's `filing_status` becomes `CONSUMMATED` and its `version` increments by 1. The target institution's `status` becomes `MERGED_OUT`, and a `MERGED_OUT` institution can never again be the acquirer or the target of a submitted application. Every branch whose `institution_id` is the target and whose `status` is `OPEN` is reassigned to the acquirer by rewriting its `institution_id`, which drops the target's `total_deposits_usd` and `branch_count` to 0. Every branch whose `designation_application_id` is this application and whose `status` is `DESIGNATED_FOR_DIVESTITURE` becomes `DIVESTED`. Then `total_deposits_usd`, `participant_count` and `hhi_current` are recomputed for every market touched by a reassignment or a divestiture. Finally the application's `post_closing_monitoring_status` becomes `MONITORING` when an `EXECUTED` community benefits plan exists for it, and `NOT_APPLICABLE` otherwise. Competitive analyses are frozen from this point and are not recomputed again.

A late attempt is not simply an error. When consummation is attempted and the current clock instant is strictly after `consummation_deadline_at`, the order moves `ISSUED → LAPSED` **first** and the caller then receives `ERR_CONSUMMATION_WINDOW_LAPSED`; the application stays in `filing_status` `DECIDED`. Because the lapse is recorded before the error is returned, a second attempt against the same order finds it no longer `ISSUED` and reports the own-resource state error `ERR_INVALID_DECISION_STATE` rather than the temporal one.

Core-systems conversion is planned separately. The `Filer` registers at most one conversion plan per application — a second is refused with `ERR_DUPLICATE_CONVERSION_PLAN` — naming the `application_id`, the inclusive `conversion_start_date`, the inclusive `conversion_end_date` which must be at or after the start date, and an `affected_customer_count` strictly greater than 0 giving the number of target-bank customers who will receive conversion disclosures. Registration checks the proposed window against the buffered closure window of every branch of the application whose `status` is `DESIGNATED_FOR_CLOSURE`, using the closed-interval conflict rule of §2.10, and a conflict is refused with `ERR_CONVERSION_BLACKOUT_CONFLICT`. The plan is created with `status` `DRAFT` and with `customer_disclosure_sent_at` and `disclosure_lead_days` null.

Sending the customer disclosure drives `DRAFT → DISCLOSED` and carries `disclosure_channels`, a non-empty array whose members are drawn from `MAIL`, `EMAIL`, `IN_BRANCH_NOTICE` and `ONLINE_BANKING`. `MAIL` is mandatory: a disclosure that omits it is refused with `ERR_CLOSURE_NOTICE_REQUIRED`. The service stamps `customer_disclosure_sent_at` from the logical clock and computes `disclosure_lead_days` as the number of whole UTC days from `customer_disclosure_sent_at` to `conversion_start_date`, discarding any partial day. That instant must be strictly before `conversion_start_date` and the lead time must be at least 30 days; either failure is refused with `ERR_DISCLOSURE_LEAD_INSUFFICIENT`. Only the acquirer may disclose.

Completing the conversion drives `DISCLOSED → CONVERTED` and is guarded by another entity's state: the application's approval order must already have `status` `CONSUMMATED`, and a plan that tries to convert earlier is refused with `ERR_INVALID_DECISION_STATE`. Every approval condition on that order whose `condition_type` is `SYSTEMS_CONVERSION` must have `status` `SATISFIED`, an unsatisfied one yielding `ERR_CONDITION_NOT_SATISFIED`. Conversion sets `status` to `CONVERTED` and closes the retail footprint: every branch of the application whose `status` is `DESIGNATED_FOR_CLOSURE` becomes `CLOSED`, and every affected deposit market recomputes `total_deposits_usd`, `participant_count` and `hhi_current`. A plan that is not `DRAFT` when a disclosure is attempted, or not `DISCLOSED` when a conversion is attempted, is refused with `ERR_INVALID_CONVERSION_PLAN_STATE`.

### 3.12. Post-Closing Commitment Monitoring

After closing, the acquirer reports quarterly against the executed plan. A report names its `plan_id`, a `period_label` such as "2027Q1" of between 4 and 16 characters that must be unique within the plan — a duplicate being refused with `ERR_DUPLICATE_REPORT_PERIOD` — a `period_index` that is a 1-based quarter number of at least 1, and an `achieved_by_category` map from commitment category to dollars achieved during the period, which must be non-empty and whose values must all be at least 0. The `period_index` must equal the plan's `filed_report_count` plus 1, so the previous quarter's report must already have completed review before the next may be filed; a mismatch is refused with `ERR_REPORT_PERIOD_OUT_OF_SEQUENCE`. Filing against a plan with no `EXECUTED` community benefits plan on the application is refused with `ERR_BENEFITS_PLAN_NOT_EXECUTED`. The report is created with `status` `FILED`, `filed_at` stamped from the logical clock, and `reviewed_at` and `reviewed_by_user_id` null.

Filing already computes the fulfilment figures, though it does not yet move the plan's ledger. Credit is capped per category against the line item's remaining headroom. Walking the `achieved_by_category` map, the service finds the plan's line item for each category; the headroom is that item's `committed_usd` less its current `credited_usd`, or zero when the plan has no line item in that category at all. The applied amount for the category is the lesser of the dollars achieved and that headroom. `credited_usd` on the report is the sum of the applied amounts across all categories, and `excess_uncredited_usd` is the sum of the amounts that could not be credited — whether because the category is not in the plan or because the achievement overshot the category's cap. The report also copies the plan's `measurement_basis` at filing time onto itself, and that copy, not the plan's later value, decides the outcome.

Two fulfilment percentages are computed from the same data. Under the `ANNUAL_PRO_RATA` basis, each quarter is judged on its own: fulfilment is the report's `credited_usd` divided by the plan's frozen `quarterly_target_total_usd`, multiplied by 100 and rounded half-up to two decimal places. Under the `CUMULATIVE_TO_DATE` basis, a strong quarter carries a weak one: take the sum of `credited_usd` across the plan's reports whose `period_index` is at or below this report's `period_index` and whose `status` is `ACCEPTED` or `DEFICIENT`, add this report's own `credited_usd` so that it is counted exactly once, then divide by the plan's frozen `quarterly_target_total_usd` multiplied by this report's `period_index`, multiply by 100, and round half-up to two decimal places. The value under the report's own `measurement_basis` is stored as `fulfillment_pct`; the value under the other basis is stored as `alternate_fulfillment_pct`, which is disclosure only and never drives an outcome. Identical report data can be accepted on one basis and found deficient on the other, and the plan's stored basis is what decides.

Review is the `ComplianceMonitor`'s act and takes no input at all — the outcome is derived by the server. The plan must have `status` `EXECUTED`. When the report's `fulfillment_pct` is at least 90.00 the report moves `FILED → ACCEPTED`; when it is strictly below 90.00 the report moves `FILED → DEFICIENT`. Either way `reviewed_at` is stamped from the logical clock, `reviewed_by_user_id` records the acting `X-User-ID`, the report's `credited_usd` is applied to each `CommitmentLineItem`'s `credited_usd` capped per item at that item's `committed_usd`, the plan's `credited_to_date_usd` increases by the report's `credited_usd` while its `remaining_commitment_usd` decreases by exactly the same amount, and the plan's `filed_report_count` increments by 1. Crediting happens on a deficient review just as on an accepted one — falling short of the target does not forfeit the dollars actually delivered.

The two outcomes then diverge on the compliance counters. An acceptance resets the plan's `consecutive_deficient_periods` to 0 and recomputes `compliance_status`. A deficiency increments `consecutive_deficient_periods` by 1 and recomputes `compliance_status` from it: a run of 0 is `COMPLIANT`, a run of exactly 1 is `WATCH`, and a run of 2 or more is `DEFICIENT`. When that run reaches 2, the cascade continues two links further: the `OPEN` approval condition on the application's order whose `condition_type` is `COMMUNITY_BENEFITS` and whose `timing` is `POST_CLOSING` moves `OPEN → BREACHED`, and — caused by that breach — the application's `post_closing_monitoring_status` becomes `ESCALATED`.

A review can be undone. Reopening drives `ACCEPTED → FILED` or `DEFICIENT → FILED`, and is permitted only when no later report of the same plan has been reviewed; otherwise it is refused with `ERR_INVALID_REPORT_STATE`, as is a reopen of a report that is already `FILED` or a review of a report that is not `FILED`. Reopening clears `reviewed_at` and `reviewed_by_user_id` to null, removes from each line item's `credited_usd` exactly the amount applied to it at review, returns the plan's `credited_to_date_usd` and `remaining_commitment_usd` to their pre-review values, and decrements `filed_report_count` by 1. Reopening a deficient review additionally decrements `consecutive_deficient_periods` by 1 and recomputes `compliance_status`; if that drops the run below 2, an approval condition that this review had breached returns `BREACHED → OPEN` and the application's `post_closing_monitoring_status` returns to `MONITORING`. Reopening an accepted review likewise recomputes `compliance_status` from the restored counters. The ledger identity that `credited_to_date_usd` plus `remaining_commitment_usd` equals `total_committed_usd` holds before the review and after the reopen alike.

A breach is curable by hand as well. Once a later report has been accepted, the `ComplianceMonitor` may drive the condition `BREACHED → SATISFIED`, provided the plan's `consecutive_deficient_periods` is back at 0 and its `compliance_status` is not `DEFICIENT`. The cure stamps `satisfied_at` and `satisfied_by_user_id`, and once no condition of that order is `BREACHED` the application's `post_closing_monitoring_status` returns to `MONITORING`. The three post-closing monitoring postures are `NOT_APPLICABLE`, `MONITORING` and `ESCALATED`.

### 3.13. The Consolidated Clearance Read

Casework needs one place to see whether an application is ready to move. A computed clearance summary, available to every role but `PublicCommenter`, assembles the whole picture without mutating anything. It reports the `application_id`; the application's `competitive_posture`; `worst_screen_result`, the most severe `screen_result` across the application's analyses; `max_hhi_delta_unmitigated`, the largest `hhi_delta_unmitigated` across them; `total_required_divestiture_usd` and `total_designated_divestiture_usd`, the sums of `required_divestiture_deposits_usd` and of `designated_divestiture_deposits_usd` across them; `all_markets_mitigated`, true only when every analysis has `mitigation_satisfied` true; `current_regulatory_cet1_pct` and `current_regulatory_capital_flag`, taken from the `CURRENT` `REGULATORY_ADJUSTED` schedule's `pro_forma_cet1_ratio_pct` and `capital_adequacy_flag`; `substantive_protest_count` and `unresolved_protest_count` as the application carries them; `granted_hearing_count`, the number of hearing requests on the application whose `status` is `GRANTED`; `earliest_decision_at`; `expedited_eligible`, applying the four expedited tests of §3.10 to the application as it currently stands; and `projected_waiting_period_days`, the waiting period the same arithmetic would produce were the order issued now.

## 4. Endpoint Definitions

Operations that bring a new, independently addressable record into existence — registering an institution, creating a deposit market or a branch, opening a merger application, building a pro forma capital schedule, running a competitive analysis, opening a comment period, filing a comment, petitioning for a hearing, proposing a benefits plan, adding a commitment line item, issuing a decision, attaching a condition, registering a conversion plan or filing a performance report — return `201 Created`. Every operation that modifies an existing record, including all state-transition actions, all designations and rescissions, and every read, returns `200 OK`. There is no shared URL prefix; all collections are mounted at the service root. In the table below, "Any" means all five roles are authorized.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/institutions` | Register a bank that can act as an acquirer, a target or a market participant | CaseAnalyst |
| GET    | `/institutions/{id}` | Read one institution including its derived deposit total and branch count | Any |
| GET    | `/institutions` | List institutions, optionally filtered by charter type, regulator or status | Any |
| POST   | `/deposit-markets` | Create a deposit market (an MSA or a rural county) in which concentration is measured | CaseAnalyst |
| GET    | `/deposit-markets/{id}` | Read one deposit market with its current aggregate deposits and index | Any |
| GET    | `/deposit-markets` | List deposit markets | Any |
| POST   | `/branches` | Add a branch with its deposit balance to an institution in a market | CaseAnalyst |
| GET    | `/branches/{id}` | Read one branch including its closure-notice lead days | Any |
| GET    | `/branches` | List branches filtered by institution, market, designating application or status | Any |
| POST   | `/branches/{id}/designate` | Designate a branch of either party for divestiture or for closure under an application | Filer |
| POST   | `/branches/{id}/rescind-designation` | Withdraw a divestiture or closure designation and restore the branch to open | Filer |
| POST   | `/merger-applications` | Open a merger application in draft between an acquirer and a target | Filer |
| GET    | `/merger-applications/{id}` | Read one merger application with all of its derived review fields | Any |
| GET    | `/merger-applications` | List merger applications filtered by acquirer, target or filing status | Any |
| PATCH  | `/merger-applications/{id}` | Amend the transaction structure or the examiner scores of an undecided application | Filer, CaseAnalyst |
| POST   | `/merger-applications/{id}/submit` | File the application with the regulator; runs the full submission gate | Filer |
| POST   | `/merger-applications/{id}/accept` | Accept a filed application for substantive review and open the public comment period | CaseAnalyst |
| POST   | `/merger-applications/{id}/return-for-amendment` | Return a filed or in-review application to the filer for amendment | CaseAnalyst |
| POST   | `/merger-applications/{id}/recommend` | Record the case analyst's recommendation once review is complete | CaseAnalyst |
| GET    | `/merger-applications/{id}/clearance-summary` | Computed read: the consolidated competitive, capital, protest and commitment posture | CaseAnalyst, ApprovingOfficial, ComplianceMonitor, Filer |
| POST   | `/pro-forma-schedules` | Build a pro forma capital schedule on one of the two bases, superseding the prior current schedule of that basis | Filer, CaseAnalyst |
| GET    | `/pro-forma-schedules/{id}` | Read one pro forma capital schedule | CaseAnalyst, ApprovingOfficial, ComplianceMonitor, Filer |
| GET    | `/pro-forma-schedules` | List pro forma capital schedules filtered by application, basis or status | CaseAnalyst, ApprovingOfficial, ComplianceMonitor, Filer |
| POST   | `/competitive-analyses` | Run the deposit-market concentration screen for one market of an application | CaseAnalyst |
| GET    | `/competitive-analyses/{id}` | Read one competitive analysis with its pre, post and mitigated concentration figures | Any |
| GET    | `/competitive-analyses` | List competitive analyses filtered by application, market or screen result | Any |
| POST   | `/comment-periods` | Open an additional public comment period for an application | CaseAnalyst |
| GET    | `/comment-periods/{id}` | Read one public comment period with its comment and protest counts | Any |
| GET    | `/comment-periods` | List public comment periods filtered by application or status | Any |
| POST   | `/comment-periods/{id}/close` | Close a public comment period once no hearing request against it is still pending | CaseAnalyst |
| POST   | `/public-comments` | File a public comment or protest against an application during a comment period | PublicCommenter |
| GET    | `/public-comments/{id}` | Read one public comment | Any |
| GET    | `/public-comments` | List public comments filtered by period, stance or status | Any |
| POST   | `/public-comments/{id}/respond` | Acknowledge or fully respond to a comment as the filer | Filer |
| POST   | `/hearing-requests` | Request a public hearing on the basis of a substantive protest | PublicCommenter |
| GET    | `/hearing-requests/{id}` | Read one hearing request with its decision and granted extension | Any |
| GET    | `/hearing-requests` | List hearing requests filtered by application, cited comment or status | Any |
| POST   | `/hearing-requests/{id}/decide` | Grant or deny a hearing request; a grant extends the cited comment period | ApprovingOfficial |
| POST   | `/hearing-requests/{id}/withdraw` | Withdraw a pending hearing request as its original requester | PublicCommenter |
| POST   | `/community-benefits-plans` | Propose a community benefits plan, superseding the prior proposed plan | Filer |
| GET    | `/community-benefits-plans/{id}` | Read one community benefits plan with its targets, credits and compliance status | Any |
| GET    | `/community-benefits-plans` | List community benefits plans filtered by application or status | Any |
| POST   | `/commitment-line-items` | Add a dollar commitment in one category to a proposed plan | Filer |
| GET    | `/commitment-line-items/{id}` | Read one commitment line item with its pro-rata targets and credited amount | Any |
| GET    | `/commitment-line-items` | List the commitment line items of a plan | Any |
| POST   | `/community-benefits-plans/{id}/execute` | Execute a proposed plan, freezing its pro-rata targets for the monitoring period | Filer |
| POST   | `/approval-decisions` | Issue the regulator's decision on a recommended application and compute the statutory waiting period | ApprovingOfficial |
| GET    | `/approval-decisions/{id}` | Read one approval decision with its waiting period and consummation window | Any |
| GET    | `/approval-decisions` | List approval decisions filtered by application or status | Any |
| POST   | `/approval-conditions` | Attach a pre-consummation or post-closing condition to an issued decision | ApprovingOfficial |
| GET    | `/approval-conditions/{id}` | Read one approval condition | Any |
| GET    | `/approval-conditions` | List approval conditions filtered by decision, timing, status or condition type | Any |
| POST   | `/approval-conditions/{id}/satisfy` | Record a condition as satisfied, or cure a previously breached condition | ComplianceMonitor |
| POST   | `/approval-decisions/{id}/consummate` | Consummate the transaction inside the approved window | Filer |
| POST   | `/systems-conversion-plans` | Register the core-systems conversion window for an application | Filer |
| GET    | `/systems-conversion-plans/{id}` | Read one systems conversion plan with its disclosure lead days | CaseAnalyst, ApprovingOfficial, ComplianceMonitor, Filer |
| GET    | `/systems-conversion-plans` | List systems conversion plans filtered by application or status | CaseAnalyst, ApprovingOfficial, ComplianceMonitor, Filer |
| POST   | `/systems-conversion-plans/{id}/disclose` | Send the customer conversion disclosure; enforces the minimum disclosure lead time | Filer |
| POST   | `/systems-conversion-plans/{id}/convert` | Complete the systems conversion after consummation, closing every branch designated for closure | Filer |
| POST   | `/performance-reports` | File a quarterly commitment performance report against an executed plan | Filer |
| GET    | `/performance-reports/{id}` | Read one commitment performance report with both fulfilment measures | Any |
| GET    | `/performance-reports` | List commitment performance reports filtered by plan or status | Any |
| POST   | `/performance-reports/{id}/review` | Review a filed report; the server derives acceptance and applies the credits | ComplianceMonitor |
| POST   | `/performance-reports/{id}/reopen` | Reopen the most recently reviewed report, exactly reversing its credits and compliance effects | ComplianceMonitor |
| POST   | `/_clock/set_current_utc` | Set the server's logical UTC clock for test-driving temporal rules | CaseAnalyst |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_NOT_APPLICATION_FILER` | 403 |
| `ERR_NOT_REQUEST_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INSTITUTION_NOT_FOUND` | 404 |
| `ERR_MARKET_NOT_FOUND` | 404 |
| `ERR_BRANCH_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_SCHEDULE_NOT_FOUND` | 404 |
| `ERR_ANALYSIS_NOT_FOUND` | 404 |
| `ERR_COMMENT_PERIOD_NOT_FOUND` | 404 |
| `ERR_COMMENT_NOT_FOUND` | 404 |
| `ERR_HEARING_REQUEST_NOT_FOUND` | 404 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_LINE_ITEM_NOT_FOUND` | 404 |
| `ERR_DECISION_NOT_FOUND` | 404 |
| `ERR_CONDITION_NOT_FOUND` | 404 |
| `ERR_CONVERSION_PLAN_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_APPLICATION_VERSION` | 412 |
| `ERR_INVALID_APPLICATION_STATE` | 409 |
| `ERR_INVALID_BRANCH_STATE` | 409 |
| `ERR_COMMENT_PERIOD_NOT_OPEN` | 409 |
| `ERR_INVALID_HEARING_REQUEST_STATE` | 409 |
| `ERR_INVALID_PLAN_STATE` | 409 |
| `ERR_INVALID_DECISION_STATE` | 409 |
| `ERR_DECISION_ALREADY_ISSUED` | 409 |
| `ERR_INVALID_CONDITION_STATE` | 409 |
| `ERR_INVALID_CONVERSION_PLAN_STATE` | 409 |
| `ERR_INVALID_REPORT_STATE` | 409 |
| `ERR_INSTITUTION_NOT_ACTIVE` | 409 |
| `ERR_HEARING_REQUEST_PENDING` | 409 |
| `ERR_CRA_RATING_INSUFFICIENT` | 422 |
| `ERR_MANAGEMENT_ASSESSMENT_UNSATISFACTORY` | 422 |
| `ERR_CONDITION_NOT_SATISFIED` | 422 |
| `ERR_COMPETITIVE_POSTURE_BLOCKED` | 422 |
| `ERR_COMMENT_WINDOW_CLOSED` | 422 |
| `ERR_COMMENT_PERIOD_OVERLAP` | 409 |
| `ERR_CLOSURE_NOTICE_LEAD_INSUFFICIENT` | 422 |
| `ERR_CONVERSION_BLACKOUT_CONFLICT` | 409 |
| `ERR_DISCLOSURE_LEAD_INSUFFICIENT` | 422 |
| `ERR_WAITING_PERIOD_NOT_ELAPSED` | 422 |
| `ERR_CONSUMMATION_WINDOW_LAPSED` | 422 |
| `ERR_NO_MARKET_OVERLAP` | 422 |
| `ERR_NO_SUBSTANTIVE_PROTEST` | 422 |
| `ERR_MARKET_ANALYSIS_MISSING` | 422 |
| `ERR_PRO_FORMA_SCHEDULE_MISSING` | 422 |
| `ERR_BENEFITS_PLAN_NOT_EXECUTED` | 422 |
| `ERR_REGULATOR_CHARTER_MISMATCH` | 422 |
| `ERR_SELF_MERGER` | 422 |
| `ERR_DUPLICATE_MARKET_CODE` | 409 |
| `ERR_DUPLICATE_ANALYSIS` | 409 |
| `ERR_DUPLICATE_CONVERSION_PLAN` | 409 |
| `ERR_DUPLICATE_REPORT_PERIOD` | 409 |
| `ERR_REPORT_PERIOD_OUT_OF_SEQUENCE` | 422 |
| `ERR_CAPITAL_DATA_MISSING` | 422 |
| `ERR_CLOSURE_NOTICE_REQUIRED` | 422 |
| `ERR_RESPONSE_BODY_REQUIRED` | 422 |
| `ERR_PRO_FORMA_CAPITAL_INSUFFICIENT` | 422 |
| `ERR_EMPTY_BENEFITS_PLAN` | 422 |
