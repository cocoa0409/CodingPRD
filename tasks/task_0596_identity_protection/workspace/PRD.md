# Identity Theft Protection API — Product Requirements Document

## 1. Introduction

Identity theft rarely announces itself as a single event. It arrives as a scatter of weak signals — a credentials dump surfacing on a dark-web forum, a soft credit inquiry the account holder never authorised, a Social Security number appearing in a data broker's trace file — and each signal, on its own, looks like noise. The product described here exists to turn that scatter into a defensible operational record: to ingest the signals, let the protected account holder triage them, escalate the ones that turn out to be real, put a trained human on the resulting mess, and reimburse the household for what the fraud cost them.

The API is mounted under `/idp` and it is the system of record for eight interlocking concerns: the **plan tiers** a household can buy, the **enrollment and verification** of a subscriber into one of those tiers, **tri-bureau credit monitoring** and the composite score derived from it, the **alert** feed and its triage lifecycle, the **restoration case** opened when an alert is confirmed as fraud, the **specialist** who works that case and the calendar windows they book against it, the **identity-theft insurance claim** that reimburses the subscriber's out-of-pocket recovery costs, and the **protected wallet** whose lost-item reports fan out into freeze requests on every credit bureau file the subscriber holds.

Two properties make this domain harder than it first appears, and the specification below leans on both. First, almost nothing is a single-entity write: confirming a fraud alert opens a case, assigning that case consumes a specialist's caseload slot and may push the specialist out of the auto-assignment pool entirely, and paying an insurance claim can exhaust a subscriber's lifetime coverage such that their next claim submission is refused. Every one of these cascades is normative and must be implemented, not approximated. Second, a subscriber's exposure is expressed by *two* risk numbers computed from the same underlying alert data with different counting rules — a consumer-facing number that reacts to un-triaged signals, and a stricter underwriting number that only counts what the subscriber has actually confirmed as fraud, and which gates access to the insurance benefit. Implementations that collapse the two into one will pass a handful of tests and fail the rest.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries its caller identity in two HTTP headers: `X-User-Role` names the operational capacity the caller is acting in, and `X-User-ID` names the specific actor. Five roles exist, spelled exactly as follows: `Anonymous`, `Subscriber`, `RestorationSpecialist`, `ClaimsAdjuster`, and `PlatformAdmin`. A request whose `X-User-Role` is absent or is not one of these five is rejected with `ERR_UNAUTHENTICATED`. `X-User-ID` is mandatory for every role except `Anonymous`; if it is missing for any of the other four roles, the same `ERR_UNAUTHENTICATED` rejection applies. Once the caller is authenticated, the acting role must additionally appear in the authorised-role list of the endpoint being called (see §4); a role acting outside its remit is rejected with `ERR_FORBIDDEN_ROLE`.

The meaning of `X-User-ID` depends on the role, and this binding is what makes ownership checks possible.

- When `X-User-Role` is `Subscriber`, `X-User-ID` is the `id` of the acting Subscriber. Ownership checks on any resource that references a Subscriber compare the resource's owning-subscriber reference to `X-User-ID` — directly for the subscriber record itself, through `subscriber_id` for family members, bureau profiles, alerts, restoration cases, insurance claims and wallet items, and through the owning bureau profile's `subscriber_id` for thaw windows. A `Subscriber` reaching for another household's resource is rejected with `ERR_NOT_RESOURCE_OWNER`.
- When `X-User-Role` is `RestorationSpecialist`, `X-User-ID` is the `id` of the acting Specialist. For actions on a restoration case, `X-User-ID` must equal that case's `specialist_id`; for booking a work window, `X-User-ID` must equal the `specialist_id` named in the booking. A specialist reaching for a case that is not theirs is likewise rejected with `ERR_NOT_RESOURCE_OWNER`.
- When `X-User-Role` is `Anonymous`, no `X-User-ID` is required or interpreted; the role exists so that a prospective customer can read a plan, enroll, and complete verification before they have a session.
- When `X-User-Role` is `ClaimsAdjuster`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it — an approval writes it to `approved_by_user_id` on the claim — but never compares it to any entity's `id`.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. It is compared to `approved_by_user_id` only for the segregation-of-duties rule described in §3.7, and to nothing else.

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

List endpoints accept two query parameters. `limit` caps the number of items returned; it defaults to 10 when omitted, may not be smaller than 1, and may not be larger than 100. `offset` is the number of items to skip before collecting the page; it defaults to 0.

Unless a specific listing states otherwise, list results are ordered by the resource's creation timestamp ascending. Two listings deviate and say so in their own right: thaw windows are ordered by `window_start` ascending, and specialist engagements are ordered by `window_start` ascending.

Every list response reports `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object. `total_count` counts the rows matching the filter *before* the page window is applied; `has_more` is true when rows remain beyond the current window.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource in this system — plans, subscribers, family members, bureau profiles, thaw windows, alerts, specialists, restoration cases, specialist engagements, insurance claims, and wallet items — carries the same four system-managed properties:

- `id` (string): a server-minted UUID. There is no type prefix and no other encoding; the raw UUID is the identifier.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recorded when the row was first written.
- `updated_at` (string): an ISO 8601 UTC timestamp in the same format, rewritten on every mutation of the resource.
- `version` (integer): a counter that increments by exactly one on every mutation of the resource, including mutations that only touch a derived field.

That last point deserves emphasis, because much of this system's behaviour is cascading. When an alert acknowledgement recomputes a subscriber's risk numbers, the subscriber has been mutated: their `updated_at` moves and their `version` increments, even though the caller addressed the alert and not the subscriber. When assigning a case changes a specialist's derived caseload, the specialist has been mutated in exactly the same sense. Each entity named as touched by a transition in §3 increments its own `version` by one for that request, independently of the others.

Time in this system is *logical*, never wall-clock. The server keeps a single logical clock whose value at startup is exactly `2026-05-01T00:00:00Z`, and an administrator may move it forward or backward by supplying a `to_iso8601` instant; the endpoint answers with the resulting `current_utc`. Before any such call the clock reads the startup default and never falls back to real time. Everything time-derived reads this clock: `score_pulled_at` on a bureau profile, `reported_lost_at` on a wallet item, `escalation_deadline` on an alert, the `is_currently_open` evaluation on a thaw window, and the "window may not start in the past" check described in §3.3 and §3.6.

### 2.5. Validation Precedence

When several checks could reject the same request, the order in which they are evaluated is normative, because it determines *which* error the caller sees. Requests are screened in the following sequence, and the first failing check short-circuits the request:

1. Authentication — the `X-User-Role` / `X-User-ID` header rules of §2.1, rejecting with `ERR_UNAUTHENTICATED`.
2. Role authorisation — the acting role appears in the endpoint's authorised-role list, rejecting with `ERR_FORBIDDEN_ROLE`.
3. Existence — every resource named in the request path is resolved first, left to right, and only then every foreign key supplied in the request body. The rejection carries the not-found code of the *first* identifier that fails to resolve: `ERR_PLAN_NOT_FOUND`, `ERR_SUBSCRIBER_NOT_FOUND`, `ERR_FAMILY_MEMBER_NOT_FOUND`, `ERR_BUREAU_PROFILE_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_SPECIALIST_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, or `ERR_WALLET_ITEM_NOT_FOUND` as appropriate. A thaw window requested under a bureau profile that does not exist therefore surfaces `ERR_BUREAU_PROFILE_NOT_FOUND`, never a downstream error.
4. Ownership — the `Subscriber` and `RestorationSpecialist` binding rules of §2.1, rejecting with `ERR_NOT_RESOURCE_OWNER`.
5. Body schema — required fields present, enum members drawn from the declared sets, integers non-negative, `ssn_last4` exactly four decimal digits, `expenses` a non-empty array of well-formed line items. Any breach is `ERR_INVALID_REQUEST`.
6. Verification token — the enrollment-verification check of §3.1, rejecting with `ERR_INVALID_VERIFICATION_TOKEN`.
7. Optimistic concurrency — the stale-version checks of §2.6, rejecting with `ERR_STALE_CASE_VERSION` or `ERR_STALE_SPECIALIST_VERSION`.
8. State legality — the target resource is currently in a state from which the requested transition is declared (this governs alerts, restoration cases, insurance claims, bureau profiles, wallet items and subscribers alike), rejecting with `ERR_INVALID_STATE`.
9. Cross-entity state — a claim being submitted must reference a restoration case that has reached `RESOLVED`, rejecting with `ERR_CASE_NOT_RESOLVED`.
10. Enrollment gating — the rule of §2.7, rejecting with `ERR_ENROLLMENT_NOT_ACTIVE`.
11. Specialist competency — `ERR_SPECIALIST_TIER_INSUFFICIENT` (§3.6).
12. Segregation of duties — `ERR_SEGREGATION_OF_DUTIES` (§3.7).
13. Family-member ownership on alert ingestion — `ERR_FAMILY_MEMBER_MISMATCH` (§3.2).
14. Child monitoring coverage on alert ingestion — `ERR_CHILD_MONITORING_NOT_INCLUDED` (§3.2).
15. Window sanity — `ERR_INVALID_WINDOW` and `ERR_WINDOW_IN_PAST` (§3.3, §3.6).
16. Thaw-window overlap — `ERR_THAW_WINDOW_OVERLAP` (§3.3).
17. Engagement capacity — `ERR_ENGAGEMENT_CAPACITY_EXCEEDED` (§3.6).
18. Specialist caseload — `ERR_SPECIALIST_AT_CAPACITY` (§3.6).
19. Auto-assignment candidacy — `ERR_NO_ELIGIBLE_SPECIALIST` (§3.6).
20. Family size against the plan allowance — `ERR_FAMILY_LIMIT_EXCEEDED` (§3.2).
21. Insurance budget — `ERR_INSURANCE_EXHAUSTED` (§3.7).
22. Underwriting gate — `ERR_UNDERWRITING_RISK_TOO_HIGH` (§3.7).

Concretely: a claim submitted by a subscriber whose insurance is exhausted *and* whose underwriting number is too high reports `ERR_INSURANCE_EXHAUSTED`, because the budget check precedes the underwriting gate. A case-assign naming a specialist who is both under-qualified and full reports `ERR_SPECIALIST_TIER_INSUFFICIENT`, because competency precedes caseload. And an assign against a case whose subscriber is suspended reports `ERR_ENROLLMENT_NOT_ACTIVE` before any specialist check runs at all.

### 2.6. Optimistic Concurrency on Cases and Specialist Calendars

Two write paths in this system are guarded against clients acting on a view of the world they have not refreshed. Both are expressed as optimistic-concurrency checks against a parent entity's `version`, and neither is optional.

Opening an insurance claim requires the body to carry `expected_case_version`, holding the client's last observed `version` of the restoration case named by `case_id`. If that value does not equal the case's current `version`, the create is rejected with `ERR_STALE_CASE_VERSION` and HTTP 412. The reason is substantive rather than ceremonial: a case carries at most one non-terminal claim, and a newly created claim legitimately supersedes any `DRAFT` claim already sitting on that case. A client working from a stale view of the case would therefore be silently destroying a draft it has never seen. Re-reading the case is the required remedy.

Booking a work window on a specialist's calendar requires the body to carry `expected_specialist_version`, holding the client's last observed `version` of the specialist named by `specialist_id`. If that value does not equal the specialist's current `version`, the booking is rejected with `ERR_STALE_SPECIALIST_VERSION` and HTTP 412. An engagement consumes a slot of the specialist's concurrent capacity, and a client whose picture of that specialist's caseload, capacity or existing bookings is out of date cannot reason correctly about whether the slot is free.

No other endpoint in this system accepts a version field, and no other endpoint performs an optimistic-concurrency check. Reading a case or reading a specialist is how a client obtains the value it must echo back.

### 2.7. Enrollment Gating

A subscriber whose `enrollment_status` is not `ACTIVE` is, for operational purposes, frozen. Any request that would drive protection work forward on behalf of such a subscriber is rejected with `ERR_ENROLLMENT_NOT_ACTIVE`. This gate applies to: ingesting an alert, every alert triage action (acknowledge, confirm-fraud, dismiss, escalate), every restoration-case action (assign, request-info, provide-info, resolve), requesting a freeze or thaw on a bureau file, scheduling a thaw window, pushing a bureau score refresh, reporting a wallet item lost, opening an insurance claim, and submitting an insurance claim.

The gate is evaluated against the subscriber who *owns* the target resource, which is not always the subscriber in the request body — for a bureau-profile action it is the profile's `subscriber_id`, for a case action it is the case's `subscriber_id`, and for a claim it is the claim's `subscriber_id`. Reads are never gated; a suspended household can still inspect its own records. Neither is enrollment itself, verification, suspension, or reactivation gated, for the obvious reason that those are the operations that move `enrollment_status` in the first place.

### 2.8. Cascade Discipline and Derived Values

Several fields in this system are *derived*: they are never written directly by a caller, and they are recomputed from scratch whenever the facts they summarise change. `composite_credit_score`, `risk_score`, `underwriting_risk_score`, `insurance_remaining_cents` and `insurance_status` on a subscriber; `active_case_count` and `status` on a specialist; `monitoring_status` on a family member; `required_specialist_tier` on a restoration case; `is_currently_open` on a thaw window — all of these are functions of other rows, and none of them accepts client input.

Because they are recomputed rather than incrementally patched, two conservation properties hold and must survive round-trips. First, **open-caseload conservation**: summing `active_case_count` over every specialist always equals the number of restoration cases that have a specialist attached and are in one of the non-terminal working states. An assign followed by a resolve therefore returns both sides of that identity — and the specialist's derived `status` — to exactly their pre-assign values. Second, **reimbursement-budget conservation**: for every subscriber, the plan's `insurance_limit_cents` always equals `insurance_remaining_cents` plus the total of `approved_cents` over that subscriber's paid claims. Paying a claim and then reversing it must restore `insurance_remaining_cents` and `insurance_status` to their exact pre-payment values, with no drift.

### 2.9. Money, Weights and Rounding

Currency in this system is integral: every monetary field ends in `_cents` and is a whole number of cents. There are no fractional cents, at rest or in transit.

Rounding is nonetheless load-bearing, because both the composite credit score and the claim reimbursement pass through fractional intermediates. Wherever this document says a value is rounded, the rule is **round half up** — a value exactly on the midpoint rounds away from zero, to the larger magnitude. Crucially, *where* the rounding happens is part of the specification, not an implementation detail: the composite credit score rounds only the final weighted quotient, and the reimbursement calculation rounds each expense line item individually and nowhere else. Summing unrounded products and rounding once at the end produces a different number of cents and is wrong.

The two identity risk numbers are integers in the closed range from 0 to 100, clamped to those bounds after rounding.

## 3. Business Logic & Workflows

### 3.1. Plans, Enrollment, and the Verification Cascade

Everything begins with a **Plan** — the product tier a household buys. An operator registers a plan with a `tier` (`STANDARD`, `ADVANTAGE`, or `ULTIMATE`), a recurring `monthly_fee_cents` which may be zero but never negative, a strictly positive `insurance_limit_cents` naming the lifetime ceiling on identity-theft reimbursement, a `max_family_members` allowance which may be zero, a `bureau_scope` of either `SINGLE` or `TRI`, and two optional knobs: `child_monitoring_included`, a boolean defaulting to `false`, and `min_specialist_tier`, one of `TIER1`, `TIER2` or `TIER3` and defaulting to `TIER1`. The plan is readable by anyone, including unauthenticated visitors, which is what lets a prospective customer compare tiers before signing up.

Enrollment is open to unauthenticated visitors and to administrators alike. The enrolling party supplies an `email` (unique across subscribers), a `full_name`, a `date_of_birth` in `YYYY-MM-DD` form, an `ssn_last4` consisting of exactly four decimal digits, and the `plan_id` of the plan being bought. The new **Subscriber** row lands with `enrollment_status` at `PENDING_VERIFICATION` and `monitoring_status` at `NOT_ENROLLED`, and the server mints a `verification_token` which it returns on the response. At this point nothing else exists: no bureau profiles, no insurance budget (`insurance_remaining_cents` sits at 0 and `insurance_status` at `AVAILABLE`), no scores.

Verification is the single most consequential write in the system. The caller — the subscriber themself, or an anonymous holder of the token — presents `verification_token` in the body. If it does not equal the token stored on the subscriber, the request is rejected with `ERR_INVALID_VERIFICATION_TOKEN`. If it matches, five things happen in one transaction. The enrollment dimension moves `PENDING_VERIFICATION → ACTIVE`. The monitoring dimension moves `NOT_ENROLLED → PENDING_DATA`. Bureau profiles are provisioned: on a `TRI` plan, three profiles are created in this exact order — `EQUIFAX`, then `EXPERIAN`, then `TRANSUNION`; on a `SINGLE` plan, only `EQUIFAX` is created. Each profile starts with a null `credit_score`, a null `score_pulled_at`, and `freeze_status` of `UNFROZEN`. The insurance budget is provisioned: `insurance_remaining_cents` is set to the plan's `insurance_limit_cents` and `insurance_status` to `AVAILABLE`. Finally, both risk variants are computed for the first time; with no alerts on file, they land at `risk_score` of 10 and `underwriting_risk_score` of 10. The subscriber's `version` increments by one.

The two status dimensions on a Subscriber are genuinely independent, and conflating them is the most common way to get this wrong. `enrollment_status` moves only on verification, suspension and reactivation, and takes one of `PENDING_VERIFICATION`, `ACTIVE`, `SUSPENDED`. `monitoring_status` moves on verification, on score refreshes, and on suspension/reactivation, and takes one of `NOT_ENROLLED`, `PENDING_DATA`, `MONITORED`, `PAUSED`. A subscriber crossing `PENDING_DATA → MONITORED` because a bureau finally reported a score does not touch their enrollment dimension at all.

An administrator may **suspend** an `ACTIVE` subscriber — for non-payment, or a fraud hold of the platform's own — by supplying a `reason`, which is stored as `suspension_reason`. The enrollment dimension moves `ACTIVE → SUSPENDED`, and if the monitoring dimension was in `PENDING_DATA` or `MONITORED` it moves to `PAUSED`; a monitoring dimension already at `NOT_ENROLLED` is left alone. **Reactivation** is the mirror image: the enrollment dimension moves `SUSPENDED → ACTIVE`, `suspension_reason` is cleared back to null, and the monitoring dimension is restored intelligently — `PAUSED → MONITORED` when the subscriber already has a non-null `composite_credit_score`, and `PAUSED → PENDING_DATA` when they do not. Both operations increment the subscriber's `version` by one. Suspending a subscriber who is not `ACTIVE`, or reactivating one who is not `SUSPENDED`, is an `ERR_INVALID_STATE` rejection.

A consolidated read is available for a subscriber's protection posture. It answers with the `subscriber_id`, the `composite_credit_score`, the `baseline_composite_credit_score`, a `bureau_count` giving the number of bureau profiles the subscriber holds, a `scored_bureau_count` giving how many of those have actually reported a score, the current `monitoring_status`, both `risk_score` and `underwriting_risk_score`, and the `insurance_remaining_cents` with its `insurance_status`. Administrators may also list subscribers, narrowing by `plan_id` or by `enrollment_status`.

### 3.2. Family Coverage and Its Limits

A household is more than one person, and a **FamilyMember** is added under a subscriber with a `full_name`, a `date_of_birth`, an `ssn_last4` of exactly four decimal digits, and a `relationship` of either `ADULT` or `CHILD`. The owning `subscriber_id` is taken from the path, never from the body. Before the row is inserted, the count of family members already on this subscriber is compared against the plan's `max_family_members`: the insert proceeds only when the existing count is strictly less than the allowance, and is otherwise rejected with `ERR_FAMILY_LIMIT_EXCEEDED`. A plan with an allowance of zero therefore admits no family members at all.

Coverage is not the same as membership. The member's derived `monitoring_status` is `MONITORED` for every `ADULT`, and for a `CHILD` only when the subscriber's plan has `child_monitoring_included` set to true; a `CHILD` on a plan without child monitoring gets `NOT_COVERED`. Note carefully that the family-member row is still created in that case — the platform simply withholds monitoring coverage from it. What the platform will *not* do is raise an alert against an uncovered dependent: an alert naming a family member whose `monitoring_status` is `NOT_COVERED` is refused with `ERR_CHILD_MONITORING_NOT_INCLUDED`.

Alerts that name a `family_member_id` must name one that actually belongs to the `subscriber_id` given in the same body. A mismatch — a dependent of some other household — is rejected with `ERR_FAMILY_MEMBER_MISMATCH`. Family members are listable under their subscriber, ordered oldest-first by creation.

### 3.3. Bureau Files: Scores, Freezes, and Temporary Thaws

Each **BureauProfile** created by the verification cascade tracks one credit bureau's file on the subscriber, identified by its `bureau` value of `EQUIFAX`, `EXPERIAN` or `TRANSUNION`. Profiles are never created directly by a caller; they exist only as a product of verification, and the subscriber's own listing of them is ordered by creation, which is to say in the provisioning order given in §3.1.

The monitoring feed pushes a fresh pull by supplying a `credit_score`, which must be an integer between 300 and 850 inclusive. The profile records the score and stamps `score_pulled_at` with the logical clock. That refresh then drives the **composite credit score**, computed as follows. Take every bureau profile of the subscriber whose `credit_score` is non-null; profiles that have not yet reported are excluded entirely — they do not count as a zero. If that set is empty, the composite is null (not zero) and the subscriber's monitoring dimension stays at `PENDING_DATA`. Otherwise, each contributing profile carries a bureau weight: `EQUIFAX` weighs 0.35, `EXPERIAN` weighs 0.35, and `TRANSUNION` weighs 0.30. Multiply each contributing profile's `credit_score` by its bureau's weight, sum those products, and divide that sum by the total of the weights of the contributing profiles only — this renormalisation is what makes a partially-reported subscriber's composite a properly weighted average rather than a deflated one. Round that final quotient half up to a whole number; that is `composite_credit_score`.

The first refresh that yields a non-null composite is special. It carries the subscriber's monitoring dimension `PENDING_DATA → MONITORED`, and it writes `baseline_composite_credit_score` — a permanent snapshot of the composite as it stood the first time it existed. That baseline is never rewritten. Every subsequent refresh recomputes `composite_credit_score` and leaves the monitoring dimension at `MONITORED` (a `MONITORED → MONITORED` self-transition), recomputes both risk variants, and leaves the baseline exactly where it was. A refresh requires the owning subscriber's enrollment to be `ACTIVE`; each refresh increments the bureau profile's `version` and the subscriber's `version` by one apiece.

The freeze lifecycle on a bureau file is a genuine cycle, and the same confirmation endpoint completes whichever direction is currently in flight. A subscriber requests a freeze or a thaw by supplying an `action` of either `FREEZE` or `THAW`. A `FREEZE` request against an `UNFROZEN` file moves it `UNFROZEN → FREEZE_PENDING`; the bureau's callback then confirms it, moving `FREEZE_PENDING → FROZEN`. A `THAW` request against a `FROZEN` file moves it `FROZEN → THAW_PENDING`; the same callback confirms it, moving `THAW_PENDING → UNFROZEN`, and the file is available for cycling again. Requesting a freeze on a file that is not `UNFROZEN`, requesting a thaw on a file that is not `FROZEN`, or confirming a file that has nothing pending, all fail with `ERR_INVALID_STATE`. Freeze and thaw *requests* additionally require the owning subscriber's enrollment to be `ACTIVE`; the bureau callback, being a machine-to-machine confirmation of work already requested, does not. Every one of these four transitions increments the bureau profile's `version` by one.

Between a freeze and its eventual thaw, a subscriber often needs the file open for a few days — for a mortgage application, say. A **ThawWindow** books that interval against the profile: `window_start` and `window_end` are ISO 8601 UTC instants and `purpose` is free text describing the need. The window's `bureau_profile_id` comes from the path. Two temporal rules govern the booking. `window_end` must be strictly later than `window_start`, or the request fails with `ERR_INVALID_WINDOW`; and `window_start` may not precede the logical clock — a start exactly at the current logical instant is acceptable, anything earlier fails with `ERR_WINDOW_IN_PAST`. Thaw windows are **closed intervals with a capacity of one**: a new window collides with an existing window on the same profile whenever the new window's start is at or before the existing window's end *and* the existing window's start is at or before the new window's end. Windows that merely touch at an endpoint — the new one beginning at the exact instant the old one ends — therefore *do* collide, and the booking is rejected with `ERR_THAW_WINDOW_OVERLAP`. A window reports `is_currently_open` as true exactly when the logical clock lies at or between `window_start` and `window_end`, both endpoints inclusive. Windows are listed under their profile ordered by `window_start` ascending.

### 3.4. The Protected Wallet and Lost-Item Assist

The wallet vault is deliberately dumb until it isn't. A subscriber stores a card or document as a **WalletItem** with an `item_type` (one of `CREDIT_CARD`, `DEBIT_CARD`, `DRIVERS_LICENSE`, `PASSPORT`, `SSN_CARD`, `INSURANCE_CARD`), the `issuer` that granted it, and `last4` — the trailing four characters of the number. The item's `subscriber_id` comes from the path, and it lands with `status` of `ACTIVE` and a null `reported_lost_at`.

Reporting an item lost is where the assist fires. The item moves `ACTIVE → REPORTED_LOST` and stamps `reported_lost_at` with the logical clock; reporting an item that is already `REPORTED_LOST` is `ERR_INVALID_STATE`, and the owning subscriber must be `ACTIVE`. The report then fans out. An **Alert** is raised on the owning subscriber with a null `family_member_id`, a `status` of `NEW`, and a `source_detail` built by prefixing the literal text `LOST_WALLET_ITEM:` to the wallet item's `id`. The alert's classification depends on what was lost: an `SSN_CARD` produces an `alert_type` of `SSN_TRACE` at `CRITICAL` severity; a `CREDIT_CARD` or `DEBIT_CARD` produces an `ACCOUNT_TAKEOVER` alert at `HIGH` severity; anything else — a driver's licence, a passport, an insurance card — produces a `DARK_WEB` alert at `MEDIUM` severity.

A lost Social Security card triggers one further cascade: **freeze assist**. Every bureau profile of that subscriber whose `freeze_status` is `UNFROZEN` is moved to `FREEZE_PENDING`, each such profile incrementing its own `version` by one, exactly as though the subscriber had requested each freeze by hand. Profiles already frozen or already mid-cycle are left untouched. The report finishes by recomputing both of the subscriber's risk variants, and increments the wallet item's `version` and the subscriber's `version` by one apiece.

### 3.5. Alert Triage and the Two Risk Numbers

The monitoring feed ingests an **Alert** by naming the `subscriber_id` it concerns, optionally a `family_member_id` when the signal is about a dependent rather than the account holder, an `alert_type` of `DARK_WEB`, `SSN_TRACE`, `ACCOUNT_TAKEOVER` or `CREDIT_INQUIRY`, a `severity` of `LOW`, `MEDIUM`, `HIGH` or `CRITICAL`, and a `source_detail` recording where the signal came from — a breach name, a creditor's name, or the wallet-item reference described in §3.4. New alerts land in `status` `NEW`, with a null `escalation_tier`, a null `escalation_deadline`, and a null `dismissal_reason`. Ingestion immediately recomputes both risk variants and increments the subscriber's `version` by one. Alerts are listable with filters on `subscriber_id`, `family_member_id` and `status`.

Triage is the subscriber's job. They **acknowledge** a `NEW` alert, moving it `NEW → ACKNOWLEDGED`. From `ACKNOWLEDGED` the workflow forks into two mutually exclusive branches with entirely disjoint consequences.

Down the first branch, the subscriber **confirms the alert as fraud**, moving it `ACKNOWLEDGED → CONFIRMED_FRAUD`. This opens a **RestorationCase**: a new case in `status` `OPEN`, with `subscriber_id` copied from the alert, `origin_alert_id` pointing back at the alert, a null `specialist_id`, and a `required_specialist_tier` computed as described in §3.6.

Down the second branch, the subscriber **dismisses the alert** as a false positive, supplying a `dismissal_reason` which is recorded on the alert, and moving it `ACKNOWLEDGED → DISMISSED`. No restoration case is created — none, ever, on this branch — and a `DISMISSED` alert contributes nothing to either risk variant from that moment on. `DISMISSED` is terminal.

An administrator may **escalate** a confirmed-fraud alert, moving it `CONFIRMED_FRAUD → ESCALATED`; escalation is covered in detail below. And when the restoration case born from an alert eventually reaches `RESOLVED`, the system itself carries that alert to `RESOLVED` — from `CONFIRMED_FRAUD` or from `ESCALATED`, whichever it was sitting in — with `RESOLVED` being the other terminal state. Each of these five triage transitions (acknowledge, confirm-fraud, dismiss, escalate, system-resolve) recomputes both risk variants and increments the alert's `version` by one; the four caller-driven ones also increment the subscriber's `version` by one, and all four require the owning subscriber to be `ACTIVE`. Attempting a triage transition from the wrong state — dismissing a `NEW` alert, escalating one that was never confirmed — is `ERR_INVALID_STATE`.

**The identity risk score.** A subscriber's exposure is expressed by two numbers computed from the same skeleton but with different counting rules. Both start from a base of 10 points. Then, for each of the four alert types, count how many of the subscriber's alerts of that type are in a status the variant *counts*, and add that count multiplied by the type's weight: a `SSN_TRACE` weighs 25 points apiece, an `ACCOUNT_TAKEOVER` weighs 20, a `DARK_WEB` hit weighs 15, and a `CREDIT_INQUIRY` weighs 8. Next, add 10 points for every one of the subscriber's alerts — of any type — currently in `ESCALATED`; an escalated alert therefore contributes both its type weight and this escalation weight. Next, if the subscriber has a non-null `baseline_composite_credit_score` and a non-null `composite_credit_score` and the baseline exceeds the current composite by at least 40 points, add a further 12 points for the score drop. The running total is then finished per variant, rounded half up to a whole number, and clamped into the range 0 through 100.

The two variants differ in exactly two respects.

- The **LIVE** variant is the consumer-facing "how exposed are you right now" number, written to `risk_score`. It counts signals early: a `CREDIT_INQUIRY` counts from the moment it is ingested, that is in `NEW`, `ACKNOWLEDGED`, `CONFIRMED_FRAUD` or `ESCALATED`; a `DARK_WEB` hit begins counting once the subscriber acknowledges it, that is in `ACKNOWLEDGED`, `CONFIRMED_FRAUD` or `ESCALATED`; while `SSN_TRACE` and `ACCOUNT_TAKEOVER` count only in `CONFIRMED_FRAUD` or `ESCALATED`. LIVE also applies a **family-child multiplier**: if the subscriber has at least one family member whose `relationship` is `CHILD` and whose `monitoring_status` is `MONITORED`, and at least one alert naming that child as its `family_member_id` sits in `CONFIRMED_FRAUD` or `ESCALATED`, then the entire running total — base, type weights, escalation weight, score-drop weight and all — is multiplied by 1.20 before the rounding and clamping. Child identity fraud is treated as a strictly worse signal than the same fraud against an adult.
- The **UNDERWRITING** variant, written to `underwriting_risk_score`, is the number the insurance benefit is underwritten against. It counts *only* alerts the subscriber has actually confirmed as fraud — `CONFIRMED_FRAUD` or `ESCALATED` — and it applies that rule uniformly to all four alert types, so a `NEW` credit inquiry and an `ACKNOWLEDGED` dark-web hit are simply invisible to it. It never applies the family-child multiplier. On identical data, whenever any alert sits in `NEW` or `ACKNOWLEDGED`, the underwriting number is strictly the lower of the two.

Both variants are recomputed together, from scratch, on every event that could move either: every alert transition, every score refresh, verification, and a lost-wallet report.

**Escalation and its pinned order.** Escalating a confirmed-fraud alert picks an `escalation_tier`, and the order of operations here is normative because the calculation looks circular: the tier is read from `risk_score`, but an `ESCALATED` alert adds 10 points *to* `risk_score`. The pinned order resolves it. First, snapshot the subscriber's `risk_score` exactly as it is persisted *before* this request mutates anything. Second, derive the tier from that snapshot alone: the tier is `TIER3` if the snapshot is at least 70 or the alert's `severity` is `CRITICAL`; otherwise it is `TIER2` if the snapshot is at least 40 or the alert's `severity` is `HIGH`; otherwise it is `TIER1`. Third, persist the transition — the alert's `status` becomes `ESCALATED`, `escalation_tier` is written, and `escalation_deadline` is set to the logical clock advanced by the tier's service-level allowance: seventy-two hours for a `TIER1` escalation, twenty-four hours for `TIER2`, and just four hours for `TIER3`. Fourth, and only now, recompute both risk variants — the alert has become `ESCALATED`, so the escalation weight now enters the sum. Fifth, lift the floor on the origin restoration case as described in §3.6. Escalation increments the alert's `version`, the origin case's `version`, and the subscriber's `version` by one apiece.

### 3.6. Restoration: Specialists, Assignment, Engagements, and Resolution

A **Specialist** is registered with a `full_name`, a competency `tier` of `TIER1`, `TIER2` or `TIER3`, a `max_caseload` of at least one, and an optional `max_concurrent_engagements` of at least one that defaults to 1. Tiers are ranked: `TIER1` ranks 1, `TIER2` ranks 2, `TIER3` ranks 3, and "at least tier X" throughout this section means a rank at or above X's rank. A newly registered specialist starts with `active_case_count` of 0 and `status` of `AVAILABLE`.

A specialist's `status` is not settable; it is a pure function of their caseload. `active_case_count` is the number of restoration cases pointing at this specialist that are in one of the three working states — `ASSIGNED`, `IN_PROGRESS` or `PENDING_SUBSCRIBER`. Cases still `OPEN` (they have no specialist) and cases already `RESOLVED` are excluded. Whenever that count is recomputed, the specialist's `status` becomes `AT_CAPACITY` when the count is greater than or equal to `max_caseload` — the comparison is inclusive, so a specialist with a `max_caseload` of two who is holding two cases is at capacity, not one case short of it — and `AVAILABLE` otherwise. Each such derived flip increments the specialist's `version`.

**The tier floor.** When a restoration case is born from a confirmed-fraud alert, its `required_specialist_tier` is set from two inputs. The alert's severity implies a tier: `CRITICAL` implies `TIER3`, `HIGH` implies `TIER2`, and `MEDIUM` or `LOW` imply `TIER1`. The subscriber's plan also carries a floor, `min_specialist_tier`. The case's `required_specialist_tier` is whichever of those two has the *higher* rank. Escalation revisits this: when an alert is escalated, the origin case's `required_specialist_tier` is raised to whichever has the higher rank between the newly-chosen `escalation_tier` and whatever the case already required — the floor only ever goes up, never down.

**Assignment.** An administrator assigns a case, moving it `OPEN → ASSIGNED`. The body may name a `specialist_id`, or omit it and let the platform choose. When a `specialist_id` *is* named, two checks run against that specialist: their tier rank must be at or above the rank of the case's `required_specialist_tier`, or the request fails with `ERR_SPECIALIST_TIER_INSUFFICIENT`; and their `active_case_count` must be strictly below their `max_caseload`, or it fails with `ERR_SPECIALIST_AT_CAPACITY`. When `specialist_id` is omitted, the platform runs its **selection policy**. The eligibility filter admits every specialist whose `status` is `AVAILABLE`, whose tier rank is at or above the case's `required_specialist_tier` rank, and whose `active_case_count` is strictly below their `max_caseload`. If that candidate set is empty, the assign is rejected with `ERR_NO_ELIGIBLE_SPECIALIST`. Otherwise the candidates are ordered by three keys, each ascending and applied in order: first by `active_case_count`, lowest first, to spread the load; then by tier rank, lowest first, so that a `TIER3` specialist is not burned on a case a `TIER1` could handle; and finally, when both keys tie, by `created_at`, oldest first. The tie-break is `created_at` and never the specialist's `id`. The first candidate in that ordering is chosen.

Assignment then cascades. The case's `specialist_id` is written. The chosen specialist's `active_case_count` recomputes upward by one, since a non-terminal case now points at them. That new count may flip their `status` to `AT_CAPACITY`. And a specialist who has become `AT_CAPACITY` drops straight out of the eligibility filter above, so the *next* auto-assignment will not consider them at all — this is precisely how a run of assignments drains the pool. Both the case's `version` and the specialist's `version` increment by one. Assignment requires the case to be `OPEN` and the case's subscriber to be `ACTIVE`.

**Engagements.** A **SpecialistEngagement** books a work window on a specialist's calendar for one case: `specialist_id`, `case_id`, `window_start` (inclusive) and `window_end` (exclusive), together with the `expected_specialist_version` demanded by §2.6. As with thaw windows, `window_end` must be strictly after `window_start` (else `ERR_INVALID_WINDOW`) and `window_start` may not precede the logical clock (else `ERR_WINDOW_IN_PAST`). Engagement intervals are **half-open** — the window covers its start instant but not its end instant — and each is extended by a **one-hour cool-down** past its end for the purposes of capacity accounting. The specialist's aggregate capacity is `max_concurrent_engagements`: the booking is rejected with `ERR_ENGAGEMENT_CAPACITY_EXCEEDED` if, at any instant, the number of that specialist's buffer-extended engagement intervals covering that instant would exceed `max_concurrent_engagements` once the new booking is added. A practical consequence: two engagements that merely touch, the second starting exactly where the first ends, still collide for a specialist with a capacity of one, because the first one's buffer runs a full hour past its end.

Booking the *first* engagement against a case is what puts a specialist to work: the case moves `ASSIGNED → IN_PROGRESS`, incrementing its `version` by one. Booking a further engagement against a case that is already `IN_PROGRESS` or `PENDING_SUBSCRIBER` records the engagement but leaves the case's status untouched. The engagement's `specialist_id` must match the case's assigned `specialist_id`. In all cases the specialist's `version` increments by one. Engagements are listable, filterable by `specialist_id` and `case_id`, ordered by `window_start` ascending.

**The information loop.** Restoration work is a conversation. The assigned specialist requests information from the subscriber by supplying an `info_request`, which is stored on the case and moves it `IN_PROGRESS → PENDING_SUBSCRIBER`. The subscriber answers by supplying an `info_response`, stored on the case, moving it back `PENDING_SUBSCRIBER → IN_PROGRESS`. This loop may repeat any number of times; each pass increments the case's `version` by one. Only the assigned specialist may make the request, and only the owning subscriber may answer.

**Resolution.** The assigned specialist closes the case out by supplying a `resolution_summary`, moving it `IN_PROGRESS → RESOLVED`. `RESOLVED` is terminal, and it unwinds two things. The specialist's compensation: the case has left the working set, so `active_case_count` recomputes downward by one, and their `status` flips back to `AVAILABLE` if the new count is below `max_caseload`. And the cross-entity hop: the origin alert — the one whose `origin_alert_id` names it — is carried to `RESOLVED` by the system, from `CONFIRMED_FRAUD` or from `ESCALATED`, which in turn recomputes both of the subscriber's risk variants. Since a `RESOLVED` alert counts for nothing in either variant, and since an alert leaving `ESCALATED` also sheds its escalation weight, resolution measurably lowers the subscriber's exposure. Resolution increments the case's `version`, the specialist's `version`, the alert's `version` and the subscriber's `version` by one apiece. Cases are listable with filters on `subscriber_id`, `origin_alert_id`, `specialist_id` and `status`.

### 3.7. Reimbursement: Claims, Adjudication, and the Lifetime Budget

Once a restoration case is `RESOLVED`, the subscriber may seek reimbursement for what the recovery cost them. An **InsuranceClaim** is opened against the case by naming its `case_id`, the `expected_case_version` demanded by §2.6, and an `expenses` array of at least one line item. Each line item is an object carrying a `category` — one of `LEGAL_FEES`, `LOST_WAGES`, `TRAVEL`, `CHILDCARE`, `NOTARY`, `POSTAGE` — a strictly positive `amount_cents`, and a boolean `documented` recording whether the subscriber has receipts. Expenses are immutable once the claim exists. The claim lands in `status` `DRAFT`, with its `subscriber_id` copied from the case, and both `provisional_amount_cents` and `approved_cents` null.

A case holds at most one non-terminal claim, and the platform enforces that by supersession rather than refusal: creating a new claim on a case that already carries a `DRAFT` claim carries the older claim `DRAFT → SUPERSEDED` (a terminal state) and increments its `version` by one. Creating the claim also increments the case's `version` by one — which is, incidentally, exactly why the `expected_case_version` guard matters.

**Submission** carries the claim `DRAFT → SUBMITTED`, and it is the tightest gate in the system. Four conditions must hold, and their order determines the error the subscriber sees: the claim must be `DRAFT` (else `ERR_INVALID_STATE`); the referenced case must be `RESOLVED` (else `ERR_CASE_NOT_RESOLVED`); the subscriber's enrollment must be `ACTIVE` (else `ERR_ENROLLMENT_NOT_ACTIVE`); the subscriber's `insurance_status` must be `AVAILABLE` (else `ERR_INSURANCE_EXHAUSTED`); and the subscriber's `underwriting_risk_score` must be at most 75 — a score of exactly 75 passes, 76 does not (else `ERR_UNDERWRITING_RISK_TOO_HIGH`). Submission runs the reimbursement calculation in its **PROVISIONAL** variant and writes the result to `provisional_amount_cents`, the estimate the subscriber is shown, and increments the claim's `version` by one.

**The reimbursement calculation** runs in five steps, and the evaluation order is pinned. Step one, per line item, individually: multiply the item's `amount_cents` by its category's coverage percentage — `LEGAL_FEES`, `NOTARY` and `POSTAGE` are covered in full at 100 percent, `LOST_WAGES` at 80 percent, `TRAVEL` and `CHILDCARE` at 50 percent — and then by a documentation factor. A line item with `documented` true is credited in full, a factor of 1. A line item with `documented` false is credited at one half under the PROVISIONAL variant, and at zero — that is, it drops out entirely — under the FINAL variant. Round that per-item product half up to whole cents, immediately, before doing anything else with it. Step two: for each category, sum the *already-rounded* eligible amounts of every line item in that category. Step three: apply the category sublimits — `LOST_WAGES` is capped at 250,000 cents, `TRAVEL` at 100,000 cents, and `CHILDCARE` at 100,000 cents; a category's total is replaced by the smaller of itself and its sublimit. `LEGAL_FEES`, `NOTARY` and `POSTAGE` carry no sublimit and pass through untouched. Step four: sum the capped category totals across every category present in the claim to get the gross, then subtract a flat deductible of 2,500 cents, flooring the result at zero — a small claim can be reduced to nothing but never to a negative. Step five: cap the result at whatever remains of the subscriber's lifetime coverage, that is, at the smaller of the after-deductible figure and the subscriber's `insurance_remaining_cents` as it stands at the moment the variant runs.

Rounding once at the end instead of per line item in step one produces a different number of cents and is incorrect. Because the FINAL variant zeroes out undocumented items while PROVISIONAL half-credits them, a claim containing any undocumented expense always approves for strictly less than its provisional estimate — that difference is the whole point of the two variants, and subscribers are told as much.

**Adjudication** belongs to a `ClaimsAdjuster`, who takes a `SUBMITTED` claim down one of two branches. Approval carries it `SUBMITTED → APPROVED`, runs the reimbursement calculation in its **FINAL** variant, writes the result to `approved_cents`, and records the adjuster's `X-User-ID` in `approved_by_user_id`. Denial carries it `SUBMITTED → DENIED` — a terminal state — records the supplied `denial_reason`, and leaves `approved_cents` null. Both increment the claim's `version` by one.

**Payment** belongs to a `PlatformAdmin`, and it is deliberately separated from adjudication. An `APPROVED` claim is disbursed, carrying it `APPROVED → PAID`, but only if the paying administrator's `X-User-ID` differs from the `approved_by_user_id` stored on the claim. An operator attempting to pay a claim they themselves approved is refused with `ERR_SEGREGATION_OF_DUTIES` — the same human may not both authorise and disburse. Payment then cascades into the budget: the subscriber's `insurance_remaining_cents` is recomputed as the plan's `insurance_limit_cents` minus the total of `approved_cents` across every one of that subscriber's claims currently in `PAID` — claims in `DRAFT`, `SUBMITTED`, `APPROVED`, `DENIED`, `REVERSED` or `SUPERSEDED` contribute nothing. If the recomputed remaining reaches zero or below, `insurance_status` becomes `EXHAUSTED`; a remaining of exactly zero *is* exhausted. And an exhausted subscriber can submit no further claims: their next submission is refused with `ERR_INSURANCE_EXHAUSTED`. Payment increments the claim's `version` and the subscriber's `version` by one apiece.

**Reversal** is the compensating action. An administrator claws back a `PAID` claim by supplying a `reversal_reason`, carrying it `PAID → REVERSED` — terminal. The claim leaves the paid set, so `insurance_remaining_cents` recomputes by the same rule and returns to precisely its pre-payment value, and `insurance_status` returns to `AVAILABLE` whenever the recomputed remaining is above zero. Pay-then-reverse must leave the budget bit-for-bit where it started. Reversal increments the claim's `version` and the subscriber's `version` by one apiece. Claims are listable with filters on `subscriber_id`, `case_id` and `status`.

## 4. Endpoint Definitions

Operations that bring a brand-new resource into existence return `201 Created`. Operations that modify an existing resource — every state transition, every cascade trigger, and the logical-clock control — return `200 OK`. Reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/idp/plans` | Create a protection plan tier | PlatformAdmin |
| GET | `/idp/plans/{id}` | Read a plan | Anonymous, Subscriber, PlatformAdmin, ClaimsAdjuster, RestorationSpecialist |
| POST | `/idp/subscribers` | Enroll a subscriber and mint the verification token | Anonymous, PlatformAdmin |
| GET | `/idp/subscribers` | List subscribers, filterable by plan and enrollment status | PlatformAdmin, ClaimsAdjuster |
| GET | `/idp/subscribers/{id}` | Read a subscriber | Subscriber, PlatformAdmin, ClaimsAdjuster, RestorationSpecialist |
| POST | `/idp/subscribers/{id}/verify` | Consume the verification token; activate enrollment and provision bureau profiles | Anonymous, Subscriber |
| POST | `/idp/subscribers/{id}/suspend` | Suspend enrollment | PlatformAdmin |
| POST | `/idp/subscribers/{id}/reactivate` | Lift a suspension | PlatformAdmin |
| GET | `/idp/subscribers/{id}/credit-summary` | Computed read: composite score, bureau coverage, both risk variants, insurance budget | Subscriber, PlatformAdmin, ClaimsAdjuster |
| POST | `/idp/subscribers/{id}/family-members` | Add a family member under the plan allowance | Subscriber, PlatformAdmin |
| GET | `/idp/subscribers/{id}/family-members` | List a subscriber's family members | Subscriber, PlatformAdmin, ClaimsAdjuster |
| GET | `/idp/subscribers/{id}/bureau-profiles` | List a subscriber's bureau profiles | Subscriber, PlatformAdmin, ClaimsAdjuster |
| GET | `/idp/bureau-profiles/{id}` | Read one bureau profile | Subscriber, PlatformAdmin, ClaimsAdjuster |
| POST | `/idp/bureau-profiles/{id}/score-refresh` | Push a fresh score pull for this bureau file | PlatformAdmin |
| POST | `/idp/bureau-profiles/{id}/freeze-request` | Request a freeze or a thaw of this bureau file | Subscriber, PlatformAdmin |
| POST | `/idp/bureau-profiles/{id}/confirm` | Bureau callback confirming whichever freeze/thaw request is pending | PlatformAdmin |
| POST | `/idp/bureau-profiles/{id}/thaw-windows` | Schedule a temporary thaw interval on a frozen bureau file | Subscriber, PlatformAdmin |
| GET | `/idp/bureau-profiles/{id}/thaw-windows` | List a profile's thaw windows | Subscriber, PlatformAdmin |
| POST | `/idp/subscribers/{id}/wallet-items` | Store a card or document in the protected wallet | Subscriber, PlatformAdmin |
| GET | `/idp/subscribers/{id}/wallet-items` | List a subscriber's wallet items | Subscriber, PlatformAdmin |
| POST | `/idp/wallet-items/{id}/report-lost` | Lost-wallet assist: flag the item, raise an alert, fire freeze assist | Subscriber, PlatformAdmin |
| POST | `/idp/alerts` | Monitoring-feed ingestion of a new alert | PlatformAdmin |
| GET | `/idp/alerts` | List alerts, filterable by subscriber, family member and status | Subscriber, PlatformAdmin, ClaimsAdjuster, RestorationSpecialist |
| GET | `/idp/alerts/{id}` | Read one alert | Subscriber, PlatformAdmin, ClaimsAdjuster, RestorationSpecialist |
| POST | `/idp/alerts/{id}/acknowledge` | Acknowledge a new alert | Subscriber, PlatformAdmin |
| POST | `/idp/alerts/{id}/confirm-fraud` | Confirm the alert as fraud; opens a restoration case | Subscriber, PlatformAdmin |
| POST | `/idp/alerts/{id}/dismiss` | Dismiss the alert as a false positive | Subscriber, PlatformAdmin |
| POST | `/idp/alerts/{id}/escalate` | Escalate a confirmed-fraud alert | PlatformAdmin |
| GET | `/idp/restoration-cases` | List restoration cases, filterable by subscriber, origin alert, specialist and status | Subscriber, PlatformAdmin, RestorationSpecialist, ClaimsAdjuster |
| GET | `/idp/restoration-cases/{id}` | Read one restoration case | Subscriber, PlatformAdmin, RestorationSpecialist, ClaimsAdjuster |
| POST | `/idp/restoration-cases/{id}/assign` | Assign a specialist, explicitly or by selection policy | PlatformAdmin |
| POST | `/idp/restoration-cases/{id}/request-info` | Assigned specialist asks the subscriber for information | RestorationSpecialist |
| POST | `/idp/restoration-cases/{id}/provide-info` | Subscriber responds; the case loops back to work | Subscriber |
| POST | `/idp/restoration-cases/{id}/resolve` | Assigned specialist closes the case out | RestorationSpecialist |
| POST | `/idp/specialists` | Register a restoration specialist | PlatformAdmin |
| GET | `/idp/specialists/{id}` | Read one specialist | PlatformAdmin, RestorationSpecialist, ClaimsAdjuster |
| POST | `/idp/specialist-engagements` | Book a work window on a specialist's calendar for one case | PlatformAdmin, RestorationSpecialist |
| GET | `/idp/specialist-engagements` | List engagements, filterable by specialist and case | PlatformAdmin, RestorationSpecialist |
| GET | `/idp/specialist-engagements/{id}` | Read one engagement | PlatformAdmin, RestorationSpecialist |
| POST | `/idp/insurance-claims` | Open a draft reimbursement claim against a resolved case | Subscriber |
| GET | `/idp/insurance-claims` | List claims, filterable by subscriber, case and status | Subscriber, PlatformAdmin, ClaimsAdjuster |
| GET | `/idp/insurance-claims/{id}` | Read one claim | Subscriber, PlatformAdmin, ClaimsAdjuster |
| POST | `/idp/insurance-claims/{id}/submit` | Submit the claim; computes the provisional reimbursement | Subscriber |
| POST | `/idp/insurance-claims/{id}/approve` | Adjuster approves; computes the final reimbursement | ClaimsAdjuster |
| POST | `/idp/insurance-claims/{id}/deny` | Adjuster denies the claim | ClaimsAdjuster |
| POST | `/idp/insurance-claims/{id}/pay` | Disburse an approved claim, subject to segregation of duties | PlatformAdmin |
| POST | `/idp/insurance-claims/{id}/reverse` | Claw back a paid claim and restore the budget | PlatformAdmin |
| POST | `/idp/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSCRIBER_NOT_FOUND` | 404 Not Found |
| `ERR_FAMILY_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_BUREAU_PROFILE_NOT_FOUND` | 404 Not Found |
| `ERR_ALERT_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_SPECIALIST_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_WALLET_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_VERIFICATION_TOKEN` | 422 Unprocessable Entity |
| `ERR_STALE_CASE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_SPECIALIST_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CASE_NOT_RESOLVED` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_SPECIALIST_TIER_INSUFFICIENT` | 409 Conflict |
| `ERR_SPECIALIST_AT_CAPACITY` | 409 Conflict |
| `ERR_NO_ELIGIBLE_SPECIALIST` | 409 Conflict |
| `ERR_ENGAGEMENT_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_THAW_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_WINDOW_IN_PAST` | 422 Unprocessable Entity |
| `ERR_FAMILY_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_FAMILY_MEMBER_MISMATCH` | 409 Conflict |
| `ERR_CHILD_MONITORING_NOT_INCLUDED` | 409 Conflict |
| `ERR_INSURANCE_EXHAUSTED` | 409 Conflict |
| `ERR_UNDERWRITING_RISK_TOO_HIGH` | 409 Conflict |
