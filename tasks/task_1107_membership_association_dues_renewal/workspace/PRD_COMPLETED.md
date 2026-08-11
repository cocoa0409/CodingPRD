# Membership Dues & Renewal Administration API — Product Requirements Document

## 1. Introduction

This document specifies the Membership Dues & Renewal Administration API for a professional membership association. The association supports multiple membership categories (for example `PROFESSIONAL`, `ASSOCIATE`, `STUDENT`, `RETIRED`, and `LIFE`), bills members on either an anniversary-anchored or calendar-anchored annual cycle, shares a configurable portion of national dues with the member's home chapter, and enforces a strict lifecycle around grace, lapse, reinstatement, resignation, and expulsion.

The platform's day-to-day burden sits in three places. First, the pricing engine must produce deterministic dues amounts across two renewal-cycle modes and three proration methods, must apply a chapter share in basis points against every settled invoice, and must enforce advance-notice rules whenever dues increase year over year. Second, the lifecycle engine must manage grace windows and reinstatement windows that are category-specific, must propagate suspension and revocation of member benefits, and must honor auto-renewal consent with retry caps and hard-decline handling. Third, the fiscal ledgers must distinguish dues revenue — which accrues against a member's `lifetime_dues_paid_cents` — from non-dues revenue such as conference registrations, publication sales, certification fees, and donations, which is tracked separately and never commingles with the dues ledger.

This PRD is the sole specification an implementer reads. It defines the structural API contract in §2, walks the business workflows in §3, lists the HTTP endpoint surface in §4, and catalogues every error code in §5. All resources are mounted under the `/api` prefix.

## 2. Global Specifications & System-Wide Principles

This section enumerates the system-wide rules that apply uniformly across every endpoint and every entity.

### 2.1. User and Role-Based Access Control

Every API request carries two mandatory headers: `X-User-ID` identifies the acting user, and `X-User-Role` declares their operational capacity. The system recognizes exactly three role names — `Member`, `MembershipAdministrator`, and `DuesAdministrator` — and any request arriving without a recognized role header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once the role is authenticated, the request is checked against the role-permission matrix in §4; any action outside the caller's authorized set is rejected with `ERR_FORBIDDEN` (HTTP 403).

The `X-User-ID` value is interpreted differently depending on role. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` (a `MembershipTerm`, a `DuesInvoice`, an `AutoRenewAuthorization`, a `BenefitEntitlement`, a `DirectoryListing`, a `RevenueAttribution`, a `ReinstatementRequest`) compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `MembershipAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`. When `X-User-Role` is `DuesAdministrator`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is never compared to an entity `id`.

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

List endpoints accept two query parameters, `limit` and `offset`. If `limit` is omitted it defaults to 10, with a minimum of 1 and a maximum of 100; out-of-range values are clamped into that range rather than rejected, and unparseable values fall back to the defaults. If `offset` is omitted it defaults to 0, and a negative `offset` is clamped to 0. All list endpoints sort by `created_at` ascending unless a more specific rule is stated in §3. Every paginated list response carries `limit`, `offset`, `total_count`, and `has_more` in its `meta` block. Only the two administrator list endpoints — GET `/api/members` and GET `/api/dues-invoices` — actually apply `limit` and `offset`; every other list endpoint ignores the two parameters and returns the full filtered set in a single page, reporting `limit` equal to the result count (or 10 when the result is empty), `offset` 0, and `has_more` false.

### 2.4. Common Resource Properties

Every primary resource — `MembershipCategory`, `DuesSchedule`, `Chapter`, `RenewalCyclePolicy`, `Member`, `MembershipTerm`, `DuesInvoice`, `PaymentAttempt`, `AutoRenewAuthorization`, `BenefitEntitlement`, `DirectoryListing`, `DuesIncreaseNotice`, `RevenueAttribution`, and `ReinstatementRequest` — carries a standard envelope of system-managed fields:

- `id` — a server-minted UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set at creation and never mutated thereafter.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` — an integer starting at 1 at creation, incremented by exactly 1 on every mutation to the resource.

A mutation that ripples from one entity to another (for example, a payment settle that also bumps the member's `lifetime_dues_paid_cents`) refreshes `updated_at` and increments `version` on every entity it touches.

### 2.5. Validation Order and Error Surface

Every request is evaluated against a fixed priority order so that an early failure is never masked by a later check. The order is: (1) presence and recognition of `X-User-Role` and `X-User-ID` — failures yield `ERR_UNAUTHENTICATED`; (2) role-permission against the RBAC matrix — failures yield `ERR_FORBIDDEN`; (3) existence of every path id and every referenced body id (member, invoice, schedule, chapter, category, cycle policy, and so on) — failures yield `ERR_NOT_FOUND`; (4) `Member.email` uniqueness on member registration — failures yield `ERR_DUPLICATE_EMAIL`; (5) `MembershipCategory.code` uniqueness on category creation — failures yield `ERR_DUPLICATE_CATEGORY_CODE`; (6) target state permits the requested transition — failures yield `ERR_INVALID_STATE`; (7) optimistic-concurrency `expected_member_version` matches the member's current `version` on guarded endpoints — failures yield `ERR_STALE_VERSION`; (8) schedule-overlap check — failures yield `ERR_SCHEDULE_OVERLAP`; (9) increase-notice gap check — failures yield `ERR_INCREASE_NOTICE_GAP`; (10) category / chapter / cycle-policy active-reference check on registration — failures yield `ERR_INACTIVE_REFERENCE`; (11) payment retry-cap check — failures yield `ERR_RETRY_EXHAUSTED`; (12) auto-renew eligibility by category — failures yield `ERR_AUTO_RENEW_NOT_ALLOWED`; (13) reinstatement-window check — failures yield `ERR_REINSTATEMENT_WINDOW_EXPIRED`; (14) refund-window check — failures yield `ERR_REFUND_WINDOW_EXPIRED`; (15) revenue-attribution kind and amount sanity — failures yield `ERR_INVALID_REVENUE_KIND`; (16) refund only on settled invoices — failures yield `ERR_INVOICE_NOT_SETTLED`. When more than one rule could fire on the same request, the lower-numbered rule wins. Four endpoint-local guards sit outside this numbered list: on payment submission the member-state guard (`ERR_MEMBER_NOT_GRACE`) fires after rules (1)–(3), and the retry-cap check (11) then fires before the invoice-state check (6), so an invoice at the retry cap yields `ERR_RETRY_EXHAUSTED` even when its `payment_status` would also fail the state check; on verification the initial-invoice-settled check (`ERR_VERIFICATION_BLOCKED`) fires after the member-state check (6); on reinstatement filing the duplicate-pending check (`ERR_REINSTATEMENT_HAS_PENDING`) fires after the member-state check (6) and before the reinstatement-window check (13); on auto-renew reactivation the authorization-state check (`ERR_NO_AUTO_RENEW_ACTIVE`) stands alone. On endpoints whose path is keyed by a `DuesInvoice` id or a `DirectoryListing` id — other than the refund endpoint — the keyed resource's existence is resolved before rules (1) and (2), so an unknown keyed id yields `ERR_NOT_FOUND` even for an unauthenticated or unauthorized caller. Requests to unknown paths, and requests to known paths with an unsupported method, are rejected with `ERR_NOT_FOUND` (HTTP 404); an unexpected server failure surfaces as `error_id` `ERR_INTERNAL` with HTTP 500.

### 2.6. Hierarchical Path Validation

Any endpoint whose URL carries multiple resource identifiers — for example, a path that walks from a member to a reinstatement request, or from a dues schedule to one of its increase notices — validates identifiers strictly left-to-right. The server first confirms the leftmost id exists; only then does it check the next id to the right, and so on. The first non-existent id in the path triggers the `ERR_NOT_FOUND` rejection, and no further identifiers along that path are consulted. The same discipline applies to referenced body ids: a request that names a `category_id`, a `home_chapter_id`, or a `cycle_policy_id` is rejected with `ERR_NOT_FOUND` if any of those references does not resolve.

### 2.7. Monetary Precision and Rounding

All monetary quantities in the system are stored and transmitted as integer cents — never as floats and never as decimal strings. Whenever a calculation must round, the rule is **round half up to the nearest whole cent**. Two such rounding points exist. First, when a calendar-cycle mid-period join computes a prorated dues amount, the prorated value is rounded half-up to a whole cent. Second, when a settled invoice's chapter share is derived, the share is rounded half-up to a whole cent. The non-cent-rounded rules — caps and floors in the risk score, day counts in proration — are integer-valued and never round fractional cents.

### 2.8. Optimistic Concurrency Control on Member Mutations

Two endpoints are guarded by optimistic concurrency against the parent `Member`'s `version`. Resignation by a member and revocation of auto-renew consent by a member each accept `expected_member_version` in the request body, which is the `version` integer the client last observed on the target `Member`. The guard fires only when the field is supplied: when `expected_member_version` is present and does not match the member's current `version` at the moment the write is attempted — for example, because a renewal settle cascade, a refund, or a benefit propagation has since advanced the version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412); a request that omits the field is not rejected on concurrency grounds. No other endpoint reads this field; supplying it on any other endpoint has no effect.

### 2.9. Logical Clock and Test-Driving Endpoints

The server maintains a logical UTC clock that drives every scheduler decision: grace transitions, lapse transitions, expulsion transitions, renewal-invoice generation, auto-renew charge sweeps, and reinstatement-request expiry. The server startup default for this logical clock is `2026-05-01T00:00:00Z`, and the server MUST NOT fall back to wall-clock time before any clock-set call is received. The logical clock is frozen between clock-set calls: it never advances with wall-clock time, only when a `to_iso8601` set call arrives. A `DuesAdministrator` may advance the logical clock by submitting a `to_iso8601` instant through a dedicated test-driving capability; each advance triggers the scheduler sweep described in §3.8. A second test-driving capability, also restricted to `DuesAdministrator`, fires the renewal-cycle sweep directly without changing the clock.

## 3. Business Logic & Workflows

This section walks the system's business processes. Every state name, every field name, and every error code referenced here is binding; the HTTP surface they map to is consolidated in §4.

### 3.1. Reference Data: Categories, Chapters, and Cycle Policies

A `DuesAdministrator` seeds the system with three pillars of reference data before any member can register.

A **Membership Category** is created with a unique `code` (for example `PROFESSIONAL`, `ASSOCIATE`, `STUDENT`, `RETIRED`, or `LIFE`), a human-readable `name`, three boolean flags — `is_voting` (whether the category carries voting rights), `is_directory_eligible` (whether members of this category appear in the public directory), and `allows_auto_renew` (whether members of this category may enroll in auto-renewal) — and two integer windows: `lapse_grace_days`, the number of days after period expiry during which the member sits in `GRACE`, and `reinstatement_window_days`, the number of days after lapse during which the member may be reinstated rather than forced to re-join. Omitted boolean flags default to `false` and omitted integer windows to `0`. On creation the category's `status` is set to `ACTIVE`. A `RETIRED` category cannot be selected on new joins; the active-reference check on registration (§3.4) is what enforces that.

A **Chapter** is created with a `code` (not checked for uniqueness), a `name`, and an `is_affiliate` boolean that distinguishes affiliate (non-geographic) chapters from geographic chapters. Its `status` starts at `ACTIVE`; the model admits later moves to `SUSPENDED` or `DISSOLVED`, but no endpoint performs a chapter-status transition, and only `ACTIVE` chapters may be referenced as a member's home chapter.

A **Renewal Cycle Policy** is created with a `code` (likewise not checked for uniqueness), a `mode` of `ANNIVERSARY` or `CALENDAR`, two calendar anchor fields — `calendar_anchor_month` (an integer from 1 to 12) and `calendar_anchor_day` (an integer from 1 to 31) — that are consulted only when `mode` is `CALENDAR`, and a `proration_method` of `PRO_RATA_DAILY`, `FULL_PERIOD`, or `NONE` that decides how mid-period joins are billed. The policy's `status` begins at `ACTIVE`; the model admits a later move to `RETIRED`, but no endpoint performs a cycle-policy status transition.

### 3.2. Dues Schedules and the Increase-Notice Contract

A `DuesAdministrator` prices each category by authoring one or more **Dues Schedules**. Each schedule carries the `category_id` it prices, an `effective_from` date on which the schedule begins applying (inclusive), an `effective_to` date on which it stops applying (exclusive, and nullable for an open-ended schedule), the `annual_amount_cents` charged as base national annual dues, the `chapter_share_bps` integer in basis points (0 to 10000) of national dues remitted to the home chapter per paid invoice, and `increase_notice_days`, the required notice interval between any dues-increase broadcast and the schedule's `effective_from`. A new schedule is born in `DRAFT`.

Two cross-schedule rules guard the publish action. First, the `[effective_from, effective_to)` interval of a schedule being published must not overlap the interval of any other `PUBLISHED` schedule for the same `category_id`; an overlap is rejected with `ERR_SCHEDULE_OVERLAP`. There is one supersession carve-out: an overlap with a prior `PUBLISHED` schedule that is open-ended (`effective_to` is null) and whose `effective_from` is strictly earlier than the new schedule's `effective_from` is permitted — that prior is exactly the supersession target named below, and publishing the new schedule transitions it to `SUPERSEDED`. Overlap with a prior that has an explicit `effective_to`, or with a prior whose `effective_from` is not strictly earlier than the new schedule's `effective_from` (a back-filling publish), cannot be resolved by supersession and is rejected. Second, when the new schedule's `annual_amount_cents` exceeds that of the most recent prior `PUBLISHED` schedule for the same category (most recent by `effective_from`), a `DuesIncreaseNotice` must already have been broadcast for the new schedule (when several notices exist for it, the one with the latest `noticed_at` is consulted), and the gap between that notice's `noticed_at` and the new schedule's `effective_from`, measured in whole days with any partial day discarded, must be at least `increase_notice_days` — a gap strictly less than `increase_notice_days` is rejected with `ERR_INCREASE_NOTICE_GAP`. The boundary is inclusive: a gap exactly equal to `increase_notice_days` is allowed. When no prior `PUBLISHED` schedule exists for the category, or the new schedule's amount is less than or equal to the prior amount, the notice-gap check does not fire and no notice is required.

Broadcasting an increase notice is a separate explicit act: a `DuesAdministrator` issues a **Dues Increase Notice** against a specific schedule. The system stamps `noticed_at` with the current logical clock, mirrors the schedule's `effective_from` onto the notice, computes `audience_size` as the count of `ACTIVE` members of the schedule's category at that moment, and sets the notice `status` to `SCHEDULED`. The model admits later moves to `SENT` and `CANCELLED`, but no operation transitions a notice out of `SCHEDULED`.

Publishing a `DRAFT` schedule transitions it to `PUBLISHED`. At the moment of publication, every other `PUBLISHED` schedule for the same category transitions to `SUPERSEDED` immediately, in the same commit as the publish. A `PUBLISHED` schedule may be retired only when no `PENDING` `DuesInvoice` references it; retirement moves the schedule to `RETIRED`, a terminal state.

### 3.3. Member Registration and the Opening Term

A new member self-registers by submitting `email`, `full_name`, the target `category_id`, their `home_chapter_id`, their governing `cycle_policy_id`, and a `joined_at` timestamp; `joined_at` may be omitted, in which case it defaults to the current logical instant. The `email` must be unique across the system — a duplicate is rejected with `ERR_DUPLICATE_EMAIL`. All three foreign-key references must be `ACTIVE`: the category, the chapter, and the cycle policy are each checked, and any one of them in a non-`ACTIVE` state causes the registration to be rejected with `ERR_INACTIVE_REFERENCE`.

Successful registration does three things in one commit. The `Member` row is created with `status` set to `PENDING_VERIFICATION` and `version` initialized to 1. An opening `MembershipTerm` is created for the member with `opened_by` set to `JOIN` and `status` set to `OPEN`. Across the system, a `MembershipTerm`'s `status` may be `OPEN`, `CLOSED` (when the period is fully consumed and paid-through), or `VOID` (when the term is invalidated by administrative action); no operation transitions a term out of `OPEN`, so `CLOSED` and `VOID` are admitted by the model but never produced. Its `opened_by` is one of `JOIN`, `RENEWAL`, `REINSTATEMENT`, or `ADMIN_ADJUST`. And an initial `DuesInvoice` is generated for the opening term; the invoice's `amount_cents` is computed by the dues-pricing rule described next, the invoice's `due_at` is set to the period's `period_end` for renewals (and to the period end of the opening term for joins), `payment_status` starts at `PENDING`, `fulfillment_status` starts at `NOT_DUE`, `issued_at` is stamped, `settled_at` is left null, and the invoice pins the `dues_schedule_id` of the schedule in force at issuance so that later schedule changes do not retroactively alter the invoice. The invoice's `membership_term_id` references the opening term, and the term's `member_id` references the new member.

### 3.4. Pricing the Dues Invoice

The dues-pricing rule fires on every `DuesInvoice` creation — both the initial join invoice and every renewal invoice — and depends on the member's governing `RenewalCyclePolicy`. The schedule that supplies `annual_amount_cents` is the one whose `status` is `PUBLISHED`, whose `category_id` matches the member's `category_id`, and whose `effective_from` is on or before the current logical instant while its `effective_to` (or positive infinity when null) is strictly after that instant.

Two variants split here.

**Anniversary variant.** When the cycle policy's `mode` is `ANNIVERSARY`, the invoice always bills the full base: `amount_cents` is the schedule's `annual_amount_cents` regardless of when in the year the join or renewal occurs. The period is anchored to the member's `joined_at`: `period_start` is the most recent anniversary of `joined_at` on or before the issuance instant (or `joined_at` itself when that lies in the future), and `period_end` is exactly one year after `period_start`; anniversary arithmetic clamps February 29 to February 28 when the target year is not a leap year.

**Calendar variant.** When the cycle policy's `mode` is `CALENDAR`, the period is anchored to the policy's calendar anchor: `period_start` is the current logical date, and `period_end` is the next occurrence of `(calendar_anchor_month, calendar_anchor_day)` strictly after `period_start` — when the anchor day exceeds the length of the anchor month, the occurrence falls on that month's last day. The billed amount then depends on `proration_method`. Under `PRO_RATA_DAILY`, `days_remaining` is the integer number of days from the calendar date of `period_start` to the calendar date of `period_end`, and `days_in_year` is 366 when `period_start` falls in a leap year and 365 otherwise; `amount_cents` is the base `annual_amount_cents` multiplied by `days_remaining`, divided by `days_in_year`, and the result rounded half-up to a whole cent. Under `FULL_PERIOD`, the full base is billed regardless of how much of the period remains. Under `NONE`, the full base is likewise billed — `NONE` means no proration is applied even though the period is short.

In both variants, `chapter_share_cents` is **not** computed at issuance; it is computed later, at settle time, as described in §3.5. If no `PUBLISHED` schedule is in force for the member's category at the pricing instant, pricing fails with `ERR_NOT_FOUND` (HTTP 404); this makes an in-force schedule a hard precondition of member registration and of reinstatement filing, while the renewal sweep of §3.8 instead skips a member it cannot price.

### 3.5. Capturing Payment: Settle, Retry, and Refund

A member pays an invoice by submitting a `payment_method_token` together with a `simulated_outcome` of `SUCCEEDED`, `DECLINED_TRANSIENT`, or `DECLINED_HARD`. Each accepted submission appends a `PaymentAttempt` row to the invoice (a rejected submission appends nothing): `attempt_index` is the 1-based sequence number within the invoice, `attempted_at` is stamped from the logical clock, `outcome` echoes the simulated outcome, and `decline_code` carries the gateway decline code on a decline (null on success). Each accepted submission returns `201` with the new attempt row. The payment-attempts list endpoint returns the rows ordered by `attempt_index` ascending.

**Success path.** When the outcome is `SUCCEEDED` and the invoice is in `PENDING` or `FAILED_RETRYABLE`, the invoice transitions to `SETTLED` in `payment_status` and `COVERAGE_ACTIVE` in `fulfillment_status`. `settled_at` is stamped with the logical clock. The covered `MembershipTerm` transitions to `OPEN`. The member's `lifetime_dues_paid_cents` is incremented by the invoice's `amount_cents`. The chapter-share ledger accrues `chapter_share_cents` to the member's `home_chapter_id`, computed as the invoice's `amount_cents` multiplied by the schedule's `chapter_share_bps`, divided by 10000, rounded half-up to a whole cent; the national share is the residual, `amount_cents` minus `chapter_share_cents`. The chapter share is computed first and the national share derived by subtraction — the rounding order is binding. The member's `version` is incremented and `updated_at` refreshed. Except for the grace-recovery cascade of §3.7, settling an invoice does not advance the member's `current_period_start`/`current_period_end`; those fields move only at verification, on recovery from grace, and on reinstatement approval.

**Transient-decline path.** When the outcome is `DECLINED_TRANSIENT` and the invoice is in `PENDING` or `FAILED_RETRYABLE`, the invoice transitions to (or remains in) `FAILED_RETRYABLE` in `payment_status` while `fulfillment_status` stays `NOT_DUE`. A new `PaymentAttempt` row is appended. The member's `risk_score` is recomputed as described in §3.9. The member's `version` is incremented.

**Hard-decline path.** When the outcome is `DECLINED_HARD`, the invoice transitions to `FAILED_FINAL` in `payment_status` while `fulfillment_status` stays `NOT_DUE`; `FAILED_FINAL` is entered only through a `DECLINED_HARD` outcome. The member's `AutoRenewAuthorization`, if `ACTIVE`, transitions to `SUSPENDED_HARD_DECLINE`. The member's `risk_score` is recomputed, and the member's `version` is incremented. The retry cap is 5 failed attempts per invoice: once an invoice has accumulated 5 failed (`DECLINED_TRANSIENT` or `DECLINED_HARD`) attempts, any further payment submission on it is rejected with `ERR_RETRY_EXHAUSTED`, no attempt row is appended, and the invoice's state is left unchanged (an invoice that reached the cap on transient declines remains `FAILED_RETRYABLE`).

**Member-state guard.** A payment submission against an invoice whose owning member is not in `ACTIVE` or `GRACE` is rejected with `ERR_MEMBER_NOT_GRACE` — for example, an invoice for a member still in `PENDING_VERIFICATION`, or one already in `LAPSED`, `RESIGNED`, or `EXPELLED`. Two carve-outs apply. First, the guard does not block the initial invoice settle for a member in `PENDING_VERIFICATION` when the settle is part of the verification flow. Second, the guard does not block settling a back-dues invoice for a member in `LAPSED` while that member's `ReinstatementRequest` referencing the invoice as `back_dues_invoice_id` is still `PENDING` — §3.7 makes the back-dues invoice reaching `SETTLED` a hard precondition for reinstatement approve, and the member is necessarily `LAPSED` at that point, so payment on that specific invoice must be reachable. Outside these two carve-outs, the guard blocks arbitrary payment on members outside the billable states.

**Refund path.** A `MembershipAdministrator` may refund a settled invoice, but only while the member's `current_period_end` is still strictly in the future — a refund attempted on or after `current_period_end` is rejected with `ERR_REFUND_WINDOW_EXPIRED`; when the member has no `current_period_end` (never verified), the window check does not fire. A refund on an invoice whose `payment_status` is anything other than `SETTLED` is rejected with `ERR_INVOICE_NOT_SETTLED`. When both preconditions hold, the invoice transitions from `SETTLED` to `REFUNDED` and from `COVERAGE_ACTIVE` to `COVERAGE_ENDED`. The member's `lifetime_dues_paid_cents` is decremented by `amount_cents`. The chapter-share ledger debits `chapter_share_cents` from the member's home chapter. The member's `current_period_start` and `current_period_end` are reset to the period of the latest-ending `MembershipTerm` still covered by a remaining `SETTLED` invoice. If after the refund the member has no remaining `SETTLED` coverage, the member transitions from `ACTIVE` to `GRACE` with immediate effect and every `BenefitEntitlement` for the member transitions to `SUSPENDED`. The member's `version` is incremented.

### 3.6. Verification and the Activation Cascade

A member in `PENDING_VERIFICATION` is activated by self-service verification. The preconditions are that the member is currently in `PENDING_VERIFICATION` and that the initial `DuesInvoice` for the opening term has reached `payment_status` of `SETTLED`. If the initial invoice has not yet settled, the verification is rejected with `ERR_VERIFICATION_BLOCKED`. If the member is in any state other than `PENDING_VERIFICATION`, the verification is rejected with `ERR_INVALID_STATE`.

When verification succeeds, the member transitions from `PENDING_VERIFICATION` to `ACTIVE`. The system copies the opening `MembershipTerm`'s `period_start` and `period_end` into the member's `current_period_start` and `current_period_end`. `lifetime_dues_paid_cents` is initialized from the settled invoice. A `BenefitEntitlement` row is created for each benefit the category confers by default — drawn from the set `JOURNAL_ACCESS`, `CONFERENCE_DISCOUNT`, `CERTIFICATION_REGISTRY`, `VOTING_BALLOT`, and `DIRECTORY_LISTING`, with the chosen value recorded on the row's `benefit_code` field and with `VOTING_BALLOT` granted only when the category's `is_voting` is true — each with `granted_at` stamped and `status` set to `ACTIVE` and `suspended_at` null. A `DirectoryListing` is created for the member with `member_id` set, `display_name` defaulting from the member's `full_name`, an empty `specialty_tags` list, `is_public` defaulting to false, and `visibility_state` computed as `VISIBLE` when the category is `is_directory_eligible` and `is_public` is true, `HIDDEN_OPT_OUT` when `is_public` is false, and `HIDDEN_CATEGORY` when the category is not `is_directory_eligible`. The member's `version` is incremented by 1.

### 3.7. The Member Lifecycle: Grace, Lapse, Reinstatement, Resignation, Expulsion

The member state machine has seven states: `PENDING_VERIFICATION`, `ACTIVE`, `GRACE`, `LAPSED`, `REINSTATED`, `EXPELLED`, and `RESIGNED`. Initial state is `PENDING_VERIFICATION`; terminal states are `EXPELLED` and `RESIGNED`. `REINSTATED` is a transient flag written in the same commit that moves the member back to `ACTIVE`.

**Grace.** When the logical clock advances past the member's `current_period_end` and no `SETTLED` renewal invoice covers the next period, the scheduler transitions the member from `ACTIVE` to `GRACE`. Every `BenefitEntitlement` row for the member transitions to `SUSPENDED`. The member's `DirectoryListing` has its `visibility_state` set to `HIDDEN_LAPSE`. The member's `version` is incremented.

**Recovery from grace.** When a payment attempt on a renewal invoice succeeds and settles the renewal invoice, the member transitions from `GRACE` back to `ACTIVE`. The renewal `MembershipTerm` covering the new period was already opened by the sweep of §3.8 with `opened_by` set to `RENEWAL`, and it is that settled invoice's term whose `period_start`/`period_end` the member's `current_period_start` and `current_period_end` are advanced to. Every `BenefitEntitlement` in `SUSPENDED` transitions back to `ACTIVE`. The `DirectoryListing`'s `visibility_state` is recomputed — `VISIBLE` when `is_public` is true and the category is `is_directory_eligible`, otherwise the appropriate hidden state. The member's `lifetime_dues_paid_cents` is incremented by the renewal invoice's `amount_cents`. The member's `version` is incremented.

**Lapse.** When the logical clock advances past `current_period_end` plus the category's `lapse_grace_days` while the member is in `GRACE`, the scheduler transitions the member to `LAPSED` and records the member's lapse timestamp from the logical clock at that moment. If the member's `AutoRenewAuthorization` is `ACTIVE` and the most recent `PaymentAttempt` outcome was `DECLINED_HARD`, the authorization transitions to `SUSPENDED_HARD_DECLINE`; otherwise the authorization is unchanged. The `DirectoryListing` remains `HIDDEN_LAPSE`. The member's `version` is incremented.

**Reinstatement.** A lapsed member may file a **Reinstatement Request**, which is rejected with `ERR_REINSTATEMENT_WINDOW_EXPIRED` when filed after the category's `reinstatement_window_days` have elapsed since the lapse timestamp. Filing creates a `ReinstatementRequest` row in `PENDING` with `requested_at` stamped, and simultaneously creates a back-dues `DuesInvoice` whose `amount_cents` is computed by walking the gap chronologically: starting from the lapse date, the engine walks forward one year at a time, identifying the schedule in force at each missed period's `period_start`, applying the dues-pricing rule of §3.4 for that period against that schedule, and summing the results into the invoice total. The walk is chronological because schedule amounts may change year over year. The back-dues invoice is attached to no term (`membership_term_id` is null), pins the `dues_schedule_id` of the schedule in force at the most recent walked period, and has its `due_at` stamped with the filing instant rather than a period end. The new back-dues invoice's `id` is recorded on the request as `back_dues_invoice_id`. A second `PENDING` request for the same member is rejected with `ERR_REINSTATEMENT_HAS_PENDING`.

A `MembershipAdministrator` approves a `PENDING` request when three preconditions hold: the member is in `LAPSED`, the current logical instant is within `reinstatement_window_days` of the lapse timestamp, and the back-dues invoice has reached `SETTLED`; a failed member-state or back-dues precondition is rejected with `ERR_INVALID_STATE`, and a failed window check with `ERR_REINSTATEMENT_WINDOW_EXPIRED`. Approval transitions the request to `APPROVED`, opens a new `MembershipTerm` with `opened_by` set to `REINSTATEMENT`, moves the member from `LAPSED` through `REINSTATED` to `ACTIVE` in the same commit, transitions every `BenefitEntitlement` back to `ACTIVE`, recomputes the `DirectoryListing` `visibility_state` per category eligibility and `is_public`, and increments the member's `version`. Alternatively, a `MembershipAdministrator` may reject a `PENDING` request, transitioning it to `REJECTED` with no other cascade. Both decisions stamp `decided_at` on the request; while the request is `PENDING` the field remains null.

**Expulsion by scheduler.** When the logical clock advances past the lapse timestamp plus `reinstatement_window_days` while the member is still `LAPSED`, the scheduler transitions the member to `EXPELLED`. Any `PENDING` reinstatement request transitions to `EXPIRED`. Any `AutoRenewAuthorization` not already `REVOKED` transitions to `REVOKED`. The member's `version` is incremented.

**Resignation.** A member in `ACTIVE` or `GRACE` may resign by submitting `expected_member_version`. When the supplied version matches the member's current `version`, the member transitions to `RESIGNED`; any mismatch is rejected with `ERR_STALE_VERSION`. Resignation revokes the `AutoRenewAuthorization` (status `REVOKED`, `revoked_at` stamped), transitions every `BenefitEntitlement` to `REVOKED`, sets the `DirectoryListing` `visibility_state` to `HIDDEN_OPT_OUT`, writes off every open `DuesInvoice` — those in `PENDING` or `FAILED_RETRYABLE` transition to `WRITTEN_OFF` in `payment_status` and `COVERAGE_ENDED` in `fulfillment_status` while remaining readable for audit — and increments the member's `version`.

**Expulsion by administrator.** A `MembershipAdministrator` may expel a member in `ACTIVE`, `GRACE`, or `LAPSED`. Expulsion applies the same cascade as resignation: auto-renew revoked, entitlements revoked, directory hidden as `HIDDEN_OPT_OUT`, open invoices written off, member version incremented.

### 3.8. Auto-Renewal Consent and the Scheduler

A member whose category's `allows_auto_renew` is true may enroll in auto-renewal by submitting a `payment_method_token`. Enrollment creates an `AutoRenewAuthorization` row with `member_id` set, `authorized_at` stamped from the logical clock, `revoked_at` left null, and `status` set to `ACTIVE`. Enrollment against a category whose `allows_auto_renew` is false is rejected with `ERR_AUTO_RENEW_NOT_ALLOWED`. Enrollment is not conditioned on the member's status, and the server does not reject a second enrollment while an authorization already exists — each enrollment call appends a new row.

Revocation is OCC-guarded: the member submits `expected_member_version`, and the request is rejected with `ERR_STALE_VERSION` if it does not match the member's current `version`. Successful revocation transitions the authorization from `ACTIVE` to `REVOKED`, stamps `revoked_at`, and increments the member's `version`; revocation when no `ACTIVE` authorization exists is rejected with `ERR_INVALID_STATE`. A separate reactivation path covers the case where the authorization has been placed in `SUSPENDED_HARD_DECLINE`: the member submits a fresh `payment_method_token`, the token replaces the stored one, and the authorization transitions back to `ACTIVE`. Reactivation when the authorization is in any state other than `SUSPENDED_HARD_DECLINE` is rejected with `ERR_NO_AUTO_RENEW_ACTIVE`. A member or `MembershipAdministrator` may retrieve the member's authorization rows via the auto-renew read capability, which returns a list (one row per enrollment).

The **renewal-cycle sweep** is the engine that drives all time-based transitions. When fired — either by a clock advance or by an explicit run call from a `DuesAdministrator` — the sweep performs three groups of actions. It issues a renewal `DuesInvoice` for every `ACTIVE` or `GRACE` member whose `current_period_end` falls within the renewal lookahead window of 30 days or has already passed (so that a member who has just entered `GRACE` still has a renewal invoice to settle for the "recovery from grace" path of §3.7), computing each invoice's `amount_cents` per the pricing rule of §3.4, priced as of the member's `current_period_end` so that the new period begins exactly where the expiring period ends. Issuance is idempotent per member: the sweep skips a member when an unpaid (`PENDING` or `FAILED_RETRYABLE`) dues invoice whose `due_at` is at or after the member's `current_period_end` already exists — settled invoices do not suppress issuance — and it silently skips a member whose renewal cannot be priced because no schedule is in force. Separately, it performs an auto-renew charge attempt for every `ACTIVE` `AutoRenewAuthorization` against that member's unpaid renewal invoice — but only while the member is `ACTIVE` or `GRACE`, only once the invoice's `due_at` has been reached, and only when no prior `PaymentAttempt` exists on that invoice, so a freshly issued renewal invoice remains `PENDING` (and manually payable per §3.5) until its due date; the back-dues invoice, which pins no dues schedule, is never auto-charged, and at most one invoice is auto-charged per member per sweep. Each charge is recorded as a `PaymentAttempt` row whose simulated outcome is always `SUCCEEDED` — the sweep does not simulate declines — and the outcome cascades per §3.5. And it advances every member state transition whose time precondition has been met: `ACTIVE` to `GRACE` for members past `current_period_end` without settled coverage, `GRACE` to `LAPSED` for members past `current_period_end` plus `lapse_grace_days`, `LAPSED` to `EXPELLED` for members past the lapse timestamp plus `reinstatement_window_days`, and `PENDING` reinstatement requests to `EXPIRED` under the same window rule.

### 3.9. Risk Score, Benefits, and the Public Directory

The **member risk score** is an integer from 0 to 100 that surfaces churn risk to operators. It is recomputed at verification, on every recorded payment-attempt outcome, on refund, on reinstatement approval, and at each scheduler-driven grace or lapse transition, and only for members in `ACTIVE`, `GRACE`, or `LAPSED`; members in other states keep their last computed score. Three components sum into the score. The failed-payment component is 20 points per failed payment attempt observed in the trailing 90 days, capped at 40 points. The expiry component is 30 points minus half the integer number of days to `current_period_end` (rounded down), floored at zero — so a member more than 60 days from expiry contributes zero. The usage component is 30 points minus the number of benefit usage events in the trailing 30 days, floored at zero — so a member with 30 or more events contributes zero. No endpoint records benefit usage events, so the trailing-30-day usage count is always zero and the usage component is always 30. The three components are summed and the total clamped into the 0-to-100 range.

**Benefit suspension propagation** fires whenever the member transitions to `GRACE`, `LAPSED`, `RESIGNED`, or `EXPELLED`. For each `BenefitEntitlement` whose `status` is `ACTIVE`, the target status is `SUSPENDED` when the destination is `GRACE` or `LAPSED`, and `REVOKED` when the destination is `RESIGNED` or `EXPELLED`; `suspended_at` is stamped on suspension. The `DirectoryListing` has its `visibility_state` recomputed under the same trigger: `VISIBLE` only when the category is `is_directory_eligible`, the member has `is_public` true, and the member is in `ACTIVE`; `HIDDEN_LAPSE` when the member is in `GRACE` or `LAPSED`; `HIDDEN_OPT_OUT` when `is_public` is false or the member has resigned or been expelled; `HIDDEN_CATEGORY` when the category is not `is_directory_eligible`. Alongside the entitlement propagation, any `DuesInvoice` whose `fulfillment_status` was `COVERAGE_ACTIVE` moves to `COVERAGE_SUSPENDED` while the member is in `GRACE` or `LAPSED`, and to `COVERAGE_ENDED` when the member reaches a terminal state. The inverse fires on recovery: when the member returns to `ACTIVE` via grace recovery or reinstatement approval, every `SUSPENDED` entitlement returns to `ACTIVE` with `suspended_at` cleared, and every invoice in `COVERAGE_SUSPENDED` returns to `COVERAGE_ACTIVE`.

A member may update their own `DirectoryListing` — `display_name`, the `specialty_tags` list, and the `is_public` flag — via the directory-update capability. Each update recomputes `visibility_state` per the same rule, using the latest `is_public` and the member's current status and category eligibility.

### 3.10. Non-Dues Revenue Attribution

Non-dues revenue — conference registrations, publication sales, certification fees, donations — is recorded against the member it is attributed to, but it never touches the dues ledger. A `MembershipAdministrator` or `DuesAdministrator` records an attribution by submitting the `revenue_kind` (one of `CONFERENCE_REGISTRATION`, `PUBLICATION_SALE`, `CERTIFICATION_FEE`, `DONATION`), a positive `amount_cents`, and an `occurred_at` timestamp; `occurred_at` may be omitted, defaulting to the current logical instant. A `revenue_kind` of `DUES` is forbidden in this ledger, and a non-positive `amount_cents` is rejected; either failure surfaces as `ERR_INVALID_REVENUE_KIND`. On creation, the server derives `fiscal_period` as the `YYYY-MM` string of `occurred_at` and appends the row to the member's non-dues ledger. The member's `lifetime_dues_paid_cents` is **not** changed by these attributions — that accumulator counts settled dues invoices only.

## 4. Endpoint Definitions

Operations that create a new resource — a category, a chapter, a cycle policy, a dues schedule in `DRAFT`, an increase notice, a member, a payment attempt, an auto-renew enrollment, a reinstatement request, a revenue attribution — return `201 Created`. Operations that modify an existing resource — verification, resignation, expulsion, publish, retire, refund, auto-renew revoke, auto-renew reactivate, directory update, reinstatement approve, reinstatement reject, clock set, scheduler run — return `200 OK`. Read endpoints return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/api/membership-categories` | Create membership category | DuesAdministrator |
| GET    | `/api/membership-categories/{id}` | Get category | DuesAdministrator, MembershipAdministrator, Member |
| POST   | `/api/chapters` | Create chapter/affiliate | DuesAdministrator |
| GET    | `/api/chapters/{id}` | Get chapter | DuesAdministrator, MembershipAdministrator, Member |
| POST   | `/api/renewal-cycle-policies` | Create renewal cycle policy (ANNIVERSARY or CALENDAR) | DuesAdministrator |
| GET    | `/api/renewal-cycle-policies/{id}` | Get cycle policy | DuesAdministrator, MembershipAdministrator |
| POST   | `/api/dues-schedules` | Create dues schedule in DRAFT | DuesAdministrator |
| GET    | `/api/dues-schedules/{id}` | Get dues schedule | DuesAdministrator, MembershipAdministrator |
| GET    | `/api/membership-categories/{id}/dues-schedules` | List schedules for category | DuesAdministrator, MembershipAdministrator |
| POST   | `/api/dues-schedules/{id}/publish` | Publish a DRAFT schedule; runs increase-notice validation when amount rises | DuesAdministrator |
| POST   | `/api/dues-schedules/{id}/retire` | Retire a PUBLISHED schedule | DuesAdministrator |
| POST   | `/api/dues-schedules/{id}/increase-notices` | Broadcast a dues-increase notice for a schedule | DuesAdministrator |
| GET    | `/api/dues-schedules/{id}/increase-notices` | List notices for schedule | DuesAdministrator, MembershipAdministrator |
| POST   | `/api/members` | Register a new member; creates initial DuesInvoice and opening MembershipTerm | Member |
| GET    | `/api/members/{id}` | Get member | Member, MembershipAdministrator, DuesAdministrator |
| GET    | `/api/members` | List members with optional filters (`status`, `category_id`, `home_chapter_id`, `cycle_policy_id`, `limit`, `offset`) | MembershipAdministrator, DuesAdministrator |
| POST   | `/api/members/{id}/verify` | Mark member verified once initial invoice settles | Member |
| POST   | `/api/members/{id}/resign` | Member resigns (OCC-guarded) | Member |
| POST   | `/api/members/{id}/expel` | Administrator expels member | MembershipAdministrator |
| GET    | `/api/members/{id}/membership-terms` | List terms for member | Member, MembershipAdministrator, DuesAdministrator |
| GET    | `/api/members/{id}/dues-invoices` | List dues invoices for member (optional `payment_status` filter) | Member, MembershipAdministrator, DuesAdministrator |
| GET    | `/api/dues-invoices/{id}` | Get single invoice | Member, MembershipAdministrator, DuesAdministrator |
| GET    | `/api/dues-invoices` | Filtered list of dues invoices (optional `member_id`, `membership_term_id`, `dues_schedule_id`, `payment_status`, `limit`, `offset`) | MembershipAdministrator, DuesAdministrator |
| GET    | `/api/dues-invoices/{id}/reinstatement-requests` | List reinstatement requests whose back-dues invoice is this invoice | Member, MembershipAdministrator |
| POST   | `/api/dues-invoices/{id}/payments` | Submit payment attempt for invoice | Member |
| POST   | `/api/dues-invoices/{id}/refund` | Refund a SETTLED invoice | MembershipAdministrator |
| GET    | `/api/dues-invoices/{id}/payment-attempts` | List payment attempts for invoice | Member, MembershipAdministrator |
| POST   | `/api/members/{id}/auto-renew/enroll` | Enroll member in auto-renew | Member |
| POST   | `/api/members/{id}/auto-renew/revoke` | Revoke auto-renew consent (OCC-guarded) | Member |
| POST   | `/api/members/{id}/auto-renew/reactivate` | Reactivate after SUSPENDED_HARD_DECLINE with new payment method | Member |
| GET    | `/api/members/{id}/auto-renew` | List the member's auto-renew authorizations (one row per enrollment) | Member, MembershipAdministrator |
| GET    | `/api/members/{id}/benefit-entitlements` | List entitlements for member | Member, MembershipAdministrator |
| GET    | `/api/members/{id}/directory-listing` | Get member's directory listing (0-1 rows) | Member, MembershipAdministrator |
| PATCH  | `/api/directory-listings/{id}` | Member updates own listing | Member |
| POST   | `/api/members/{id}/reinstatement-requests` | File reinstatement request; creates back-dues invoice | Member |
| GET    | `/api/members/{id}/reinstatement-requests` | List reinstatement requests | Member, MembershipAdministrator |
| POST   | `/api/members/{id}/reinstatement-requests/{rid}/approve` | Approve reinstatement if back-dues settled | MembershipAdministrator |
| POST   | `/api/members/{id}/reinstatement-requests/{rid}/reject` | Reject reinstatement | MembershipAdministrator |
| POST   | `/api/members/{id}/revenue-attributions` | Record non-dues revenue event attributed to member | MembershipAdministrator, DuesAdministrator |
| GET    | `/api/members/{id}/revenue-attributions` | List revenue attributions (optional `fiscal_period` filter) | Member, MembershipAdministrator, DuesAdministrator |
| POST   | `/api/_clock/set_current_utc` | Advance logical clock (test-driving); startup default `2026-05-01T00:00:00Z` and no wall-clock fallback before any set call | DuesAdministrator |
| POST   | `/api/_scheduler/run_renewal_cycle` | Fire the scheduled renewal sweep | DuesAdministrator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_DUPLICATE_EMAIL` | 409 Conflict |
| `ERR_DUPLICATE_CATEGORY_CODE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SCHEDULE_OVERLAP` | 409 Conflict |
| `ERR_INCREASE_NOTICE_GAP` | 409 Conflict |
| `ERR_INACTIVE_REFERENCE` | 422 Unprocessable Entity |
| `ERR_RETRY_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_AUTO_RENEW_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_REINSTATEMENT_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_REFUND_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_INVALID_REVENUE_KIND` | 422 Unprocessable Entity |
| `ERR_INVOICE_NOT_SETTLED` | 422 Unprocessable Entity |
| `ERR_VERIFICATION_BLOCKED` | 422 Unprocessable Entity |
| `ERR_MEMBER_NOT_GRACE` | 409 Conflict |
| `ERR_REINSTATEMENT_HAS_PENDING` | 409 Conflict |
| `ERR_NO_AUTO_RENEW_ACTIVE` | 409 Conflict |
