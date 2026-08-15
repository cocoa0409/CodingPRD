# Insurance Rate Filing API — Product Requirements Document

## 1. Introduction

Every admitted-market insurer operates under a standing bargain with state regulators: before a revised rate, rule, or form may be charged to a single policyholder, the change must run a state-by-state gauntlet — prior approval in some jurisdictions, file-and-use or use-and-file in others — punctuated by objection letters, statutory response clocks, deemer provisions, mandatory lead times, and policyholder notice windows. Each deadline carries real regulatory and financial consequence, and each state insists on its own parameters for all of them. The product filing team that manages this work needs a system of record that treats those parameters as data, enforces segregation of duties between the actuaries who develop rate indications and the compliance staff who submit filings, and can prove, deadline by deadline, that every obligation was met, missed, or lawfully waived.

This document specifies the Insurance Rate Filing API, which covers that chain end to end: actuarial indication development under two calculation variants, per-state regulatory profiles, filing assembly from rate, rule, and form components with state-specific deviations, the objection and interrogatory cycle with its service-level clock, approval and deemed approval, effective-date resolution against a strictly ordered rate book, and implementation waves that re-rate the renewal book under per-policy disruption caps with a complete reversal and rescission path. A server-side logical clock — never the wall clock — drives every deadline behavior in the system, so that sweeps for overdue objections, deemed approvals, missed notices, and wave completions are fully deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and principles that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes six distinct roles: `PlatformAdmin`, `ProductActuary`, `FilingAnalyst`, `ComplianceOfficer`, `StateRegulator`, and `ImplementationLead`. A request that arrives without both headers present and well-formed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400); well-formed requires `X-User-ID` to be a non-blank string and `X-User-Role` to name exactly one of the six roles, so an unrecognized role value draws the 400, never the 403. Once identified, the caller's role must be authorized for the target operation; an attempt to perform an action outside the role's designated permissions is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403). Read-only retrieval and list operations are open to all six roles; every mutating operation is restricted to the roles named in §4.

For every role, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server never compares it against any resource's `id`. Individually: when `X-User-Role` is `ProductActuary`, the identifier may be recorded as `prepared_by_user_id` or `approved_by_user_id` on a RateIndication, but it identifies no stored user row. When `X-User-Role` is `FilingAnalyst`, the identifier may be recorded as `drafted_by_user_id` on an ObjectionResponse, again with no entity backing it. When `X-User-Role` is `ComplianceOfficer`, `StateRegulator`, `ImplementationLead`, or `PlatformAdmin`, the identifier is likewise opaque and is not persisted on any entity at all. Segregation-of-duties comparisons (see §3.2) compare these opaque identifiers to one another, never to resource identifiers.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_` followed by twenty lowercase hexadecimal characters.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, reading the server's logical clock (§2.4) rather than the wall clock.
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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. The bounds are enforced, never clamped: a `limit` that is not an integer or falls outside 1–100, or an `offset` that is not a non-negative integer, is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with ties broken by insertion order (the earliest inserted resource first).

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

List endpoints also accept optional equality filters drawn from the resource's own identifying fields — depending on the resource, some subset of `product_id`, `state_code`, `status`, `profile_id`, `indication_id`, `filing_id`, `wave_id`, `objection_id`, and `entry_type` — alongside the pagination parameters. The accepted subset is fixed per endpoint: `GET /state-profiles` accepts `product_id`, `state_code`, `status`; `GET /rate-indications` accepts `product_id`, `status`; `GET /filings` accepts `product_id`, `profile_id`, `indication_id`, `state_code`, `status`; `GET /components` and `GET /deviations` accept `filing_id`, `status`; `GET /objections` accepts `filing_id`, `status`; `GET /responses` accepts `objection_id`, `status`; `GET /waves` accepts `filing_id`, `product_id`, `status`; `GET /policies` accepts `product_id`, `wave_id`, `state_code`, `status`; and `GET /calendar-entries` accepts `filing_id`, `wave_id`, `objection_id`, `entry_type`, `status`. Query parameters outside an endpoint's accepted set are ignored.

### 2.4. The Logical Clock and the System Sweep

Time inside this API is governed by a server-side logical clock. At startup the clock reads exactly `2026-08-01T00:00:00Z`, and it never consults wall-clock time; the only way time advances is through an admin-only, test-driving capability restricted to `PlatformAdmin` that sets the clock to a supplied target instant `to_iso8601` and answers with the clock's new reading as `current_utc`. The target may be any well-formed ISO 8601 instant — explicit offsets are normalized to UTC, a naive reading is treated as UTC, and the target is not constrained to lie forward of the current reading. Every statutory and contractual deadline in the system — objection response clocks, deemer dates, notice windows, wave windows — is evaluated against this logical clock and nothing else.

Every clock set triggers the system sweep, a single deterministic pass that reconciles time-driven state across the book of work, executed in a fixed order: first, objections still in `RAISED` or `RESPONSE_DRAFTED` whose response deadline has passed move to `OVERDUE`; second, submitted filings whose deemer date has been reached with no non-terminal objection outstanding become `DEEMED_APPROVED`; third, rated renewal policies whose notice due date has passed without a notice ever being sent are bounced back to pending (§3.7); fourth, released waves whose window has closed with every assigned policy settled move to `COMPLETED`; and finally, any compliance calendar entry still `PENDING` past its tracked deadline becomes `MISSED`. The individual transitions and their side effects are specified in §3 alongside the workflows they belong to.

### 2.5. Common Resource Properties

Every resource in this API — products, state regulatory profiles, rate indications, rate filings, filing components, deviations, objections, objection responses, implementation waves, renewal policies, and compliance calendar entries — carries the same four system-managed fields:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording the last modification.
- **`version` (integer):** a system-managed integer that starts at 1 when the resource is created and increments by one on every mutation.

Any change to a resource — whether driven by a client request or by a system cascade such as a supersession, a withdrawal cascade, a wave release, or a clock sweep — refreshes that resource's `updated_at` and increments its `version`. Derived and computed fields are maintained by the server and are never accepted as client input.

### 2.6. Numeric Precision, Rounding, and Date Granularity

Rate changes and other percentage figures (such as `proposed_change_pct`, `indicated_change_pct`, and `raw_change_pct`) are decimals — 0.04 means four percent — and computed percentages are stored at exactly four decimal places, rounded half up; all intermediate values in a calculation remain unrounded until the final stored result. The book-level `balance_factor` is stored at eight decimal places, rounded half up. All premium amounts are integer cents; whenever a premium is computed it is rounded half up to a whole cent. Rounding order is pinned throughout the renewal pipeline: every per-policy premium is rounded to whole cents before any book-level aggregation, and the system never aggregates first and rounds afterward.

Calendar dates (effective dates, renewal dates, wave window bounds) use the `YYYY-MM-DD` format and are compared at date granularity; comparisons are inclusive unless a rule explicitly says otherwise. Timestamps use ISO 8601 UTC with three fractional digits, and durations that statutes express in days are applied as whole days of 86,400 seconds where a timestamp-level deadline is required.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and both declare a mandatory version field in their request payloads.

Creating a rate indication requires `expected_product_version`, carrying the version of the parent Product the client last observed. If the product's current `version` has advanced since that observation — for example because another indication was created against the product or a countrywide indication was locked, both of which advance the product's book-of-record version — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from building an indication on a product view it has not re-read.

Drafting an objection response requires `expected_objection_version`, carrying the version of the parent Objection the client last observed. If the objection's current `version` has advanced since that observation — for example because another analyst has already drafted a response, which supersedes the prior draft position — the draft is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field; optimistic concurrency applies exactly to these two operations and nowhere else.

### 2.8. Validation Order and Nested Resource Retrieval

Every request is validated against a fixed pipeline, and a request that would fail several checks surfaces the failure from the earliest stage. The evaluation order is: first, the presence and well-formedness of the identity headers (§2.1); second, role authorization for the target operation; third, request-body well-formedness — required fields present, no unknown fields, types correct, enum members valid, amounts positive, dates in ISO format — with violations rejected as `ERR_INVALID_REQUEST` (HTTP 400); fourth, the existence of every resource referenced by path identifiers and body foreign keys, resolved left to right, with the first unresolvable reference rejected as `ERR_NOT_FOUND` (HTTP 404); fifth, the optimistic-concurrency version check of §2.7 where the endpoint declares one; sixth, whether the target resource is in a state from which the requested transition exists, rejected otherwise as `ERR_INVALID_STATE` (HTTP 409); seventh, segregation of duties; eighth, the usability of referenced regulatory configuration; ninth, temporal rules such as lead times, windows, and notice deadlines; tenth, structural uniqueness and overlap rules; and finally the monetary ceilings.

Because identifiers are validated left to right, a request that names both a missing filing and a malformed component beneath it reports the filing failure first. This ordering guarantee keeps container errors from being masked by errors about their contents. A request to an unrecognized path or an unsupported method on a known path is likewise rejected as `ERR_NOT_FOUND` (HTTP 404).

### 2.9. The Compliance Calendar

Every deadline the system tracks is materialized as a ComplianceCalendarEntry, giving the filing team a single auditable calendar of obligations. Each entry carries an `entry_type` drawn from `OBJECTION_RESPONSE_DUE`, `DEEMED_DATE`, `WAVE_WINDOW`, `RENEWAL_NOTICE_DUE`, and `EFFECTIVE_DATE`; a `due_date` instant marking the deadline; and a `status` that begins at `PENDING`. Entries link back to their subject matter through `filing_id`, `wave_id`, or `objection_id`; a link that does not apply to the entry's type is null. The link convention is fixed per type: `DEEMED_DATE` and `EFFECTIVE_DATE` entries carry a `filing_id` only; `WAVE_WINDOW` and `RENEWAL_NOTICE_DUE` entries carry a `wave_id` only; and `OBJECTION_RESPONSE_DUE` entries carry both the `filing_id` and the `objection_id` of their subject.

Deadline storage follows one convention: deadlines that are date-only by nature (deemer dates, wave window ends, renewal notice due dates, effective dates) are stored at 23:59:59Z of the due day, while an objection's response deadline keeps its exact timestamp. An entry leaves `PENDING` in exactly one of three ways, recording `resolved_at` at the moment it resolves: it becomes `MET` when the obligation is satisfied on time — a response submitted by its deadline, a notice sent by its notice due date, a filing approved or deemed approved, a mark-effective completed, a wave completed; it becomes `MISSED` when the clock sweep finds the deadline passed with the obligation still unmet; and it becomes `WAIVED` when a `ComplianceOfficer` deliberately waives a pending obligation or when a cascade (a withdrawn or disapproved filing, a cancelled or reversed wave, a withdrawn objection) vacates the obligation. Only a `PENDING` entry can become `WAIVED` — a cascade or manual waiver never disturbs an entry already `MET` or `MISSED` — and a `WAIVED` entry is terminal, never resurrected by any later event. A `MISSED` entry, by contrast, can still be claimed to `MET` when its obligation is ultimately satisfied late: a mark-effective completed after the effective date, a wave completing after its window deadline, or an approval or deemed approval arriving after the deemer date each mark their entry `MET`. The specific creation and resolution triggers for each entry type are described with their workflows in §3.

### 2.10. The Rate Book and Supersession

For each pairing of product and state, the API maintains a rate book: an ordered chain of filings that have taken effect, where each link spans the half-open interval from its `actual_effective_date` (inclusive) to its `superseded_at_date` (exclusive). A new filing may enter the rate book only at the head of the chain: no currently `EFFECTIVE` filing for the same product and state may have an `actual_effective_date` on or after the incoming filing's own. An equal date is an overlap, not a succession — two filings of one rate book can never take effect on the same day — and the attempt is rejected with `ERR_RATEBOOK_OVERLAP` (HTTP 409). A strictly later date succeeds, and the incumbent `EFFECTIVE` filing is superseded in the same motion, its `superseded_at_date` set to the successor's `actual_effective_date` so the chain never gaps and never overlaps.

## 3. Business Logic & Workflows

### 3.1. Products and State Regulatory Profiles

Everything begins with the Product, the book-of-record anchor for all filing activity. A `ProductActuary` creates a product by supplying a `product_code` — a short code such as PPA for personal auto that must be unique across all products, with a duplicate rejected as `ERR_INVALID_REQUEST` (HTTP 400) — together with a display `name`. The product also maintains `current_locked_indication_id`, a pointer to the most recently locked countrywide rate indication; it remains null until the first countrywide indication locks (§3.2).

Before any filing can be prepared for a state, a `ComplianceOfficer` must register a **State Regulatory Profile** for the pairing of `product_id` and `state_code`, where `state_code` is an uppercase two-letter code. The profile captures that state's regulatory parameters: the `filing_method`, one of `PRIOR_APPROVAL` (the filing may not take effect until the regulator approves it, subject to a minimum lead time), `FILE_AND_USE` (rates may be used once filed, subject to later disapproval), or `USE_AND_FILE` (rates may be used on the proposed date even before regulator action); `min_effective_lead_days`, the minimum number of days between approval and the effective date under prior approval; `objection_response_sla_days`, the number of days the insurer has to answer a regulator's objection; `deemer_days`, the number of days after submission at which a prior-approval filing is deemed approved if the regulator has not acted — a value of zero disables the deemer entirely; `max_single_change_pct`, the state's regulatory ceiling on the rate change any single filing may propose, which also bounds per-policy disruption caps at implementation time; `renewal_notice_days`, the number of days before a renewal effective date by which the policyholder notice must be sent; and `disapproval_window_days`, the number of days after effectiveness during which a file-and-use or use-and-file filing may still be disapproved. A profile is created in `ACTIVE` status.

Only one profile may exist for a given product and state: a second attempt is rejected with `ERR_DUPLICATE_PROFILE` (HTTP 409). A `ComplianceOfficer` may suspend a profile, moving it from `ACTIVE` to `SUSPENDED`, and later reactivate it, returning it to `ACTIVE`. While a profile is `SUSPENDED`, no new rate filing may be created for that product and state — the attempt is rejected with `ERR_PROFILE_INACTIVE` (HTTP 409) — and, as §3.3 describes, an inactive profile also blocks submission of any filing prepared against it.

### 3.2. Rate Indication Development and the Actuarial Review Cycle

The actuarial heart of the system is the **Rate Indication**: the quantified, experience-based answer to "how much should this product's rates change?" A `ProductActuary` creates an indication in `DRAFT` status by submitting the experience fields: `product_id`; an optional `scope_state_code` whose omission (null) marks the indication as countrywide in scope; the calculation `variant`, either `INCURRED_CREDIBILITY` or `PAID_PURE`; `earned_premium_cents`, the on-level earned premium for the experience period; `incurred_loss_cents` and `paid_loss_cents`, the reported incurred and paid losses; `exposure_units`, the earned exposures that drive credibility; `trend_factor`, the annual loss and premium trend expressed as a decimal (0.04 for four percent); and `countrywide_change_pct`, the countrywide indicated change used as the complement of credibility. The premium, loss, and exposure fields must be positive integers; `trend_factor` and `countrywide_change_pct` are unrestricted signed decimals. The creating actuary's identity is recorded as `prepared_by_user_id`, and a fresh indication carries `review_round` 1. Because an indication is a mutation of the product's book of record, creation advances the parent product's `version` by one — and, per §2.7, the create request must carry `expected_product_version` matching the product's current `version`, failing with `ERR_STALE_VERSION` (HTTP 412) when the client's view is stale.

Both actuarial variants are computed at creation from the submitted experience fields, so the filing team can always see the road not taken. Credibility comes first: `credibility_z` is the lesser of one and the square root of the ratio of `exposure_units` to the full-credibility standard of 1,082 earned exposures — a book with 1,082 or more exposure units is fully credible. Under the `INCURRED_CREDIBILITY` variant, the incurred losses are developed to ultimate by multiplying `incurred_loss_cents` by the loss development factor 1.12; those ultimate losses are divided by the product of `earned_premium_cents` and the target loss ratio 0.68, and one is subtracted from that quotient to yield the experience indication. The countrywide complement is then projected forward by one year of trend, multiplying `countrywide_change_pct` by one plus `trend_factor`. The variant's result is the credibility-weighted blend: `credibility_z` times the experience indication, plus the complement of credibility (one minus `credibility_z`) times the trended countrywide change. Under the `PAID_PURE` variant the result is deliberately simpler: `paid_loss_cents` divided by `earned_premium_cents`, that ratio divided by the target loss ratio 0.68, minus one — no credibility blend, no trend, and no loss development apply. Whichever variant the request names is stored as `indicated_change_pct`, and the other variant's result is preserved alongside it as `alternate_change_pct`; both are stored at four decimal places, rounded half up, with all intermediate values left unrounded. The `credibility_z` factor itself is stored unrounded, at full computational precision.

Review follows a cyclic workflow. The preparer submits the draft for actuarial review, moving it from `DRAFT` to `IN_ACTUARIAL_REVIEW`. A `ProductActuary` then either approves or returns it. Approval moves the indication to `APPROVED` and records the approver's identity as `approved_by_user_id` — but segregation of duties is enforced: the approver's `X-User-ID` must differ from `prepared_by_user_id`, and a self-approval attempt is rejected with `ERR_SOD_VIOLATION` (HTTP 403). Returning the indication sends it from `IN_ACTUARIAL_REVIEW` back to `DRAFT` and increments `review_round` by one, so the revision loop `DRAFT` → `IN_ACTUARIAL_REVIEW` → `DRAFT` may repeat as many times as the work requires.

An approved indication becomes the legal basis for filings only when a `ProductActuary` locks it, moving it from `APPROVED` to `LOCKED`. Locking is exclusive within a scope: any other `LOCKED` indication for the same product and scope instantly becomes `SUPERSEDED`, the indication's terminal state. When the locked indication is countrywide (its `scope_state_code` is null), the lock additionally points the product's `current_locked_indication_id` at the newly locked indication and advances the product's `version` by one. Supersession has teeth: a filing that still references an indication which has since been superseded can no longer be submitted — the submission fails with `ERR_INDICATION_NOT_LOCKED` (HTTP 409), as §3.3 describes.

### 3.3. Assembling the Filing: Components, Deviations, and Submission

With a locked indication in hand, a `FilingAnalyst` creates a **Rate Filing** in `DRAFT` status, supplying `product_id`, the destination `state_code`, the `filing_type` (`RATE_CHANGE`, `RATE_RULE_FORM`, `RULE_ONLY`, or `FORM_ONLY`), the `proposed_change_pct` as a decimal, the requested `proposed_effective_date` in `YYYY-MM-DD` form, and the `indication_id` of the locked actuarial basis. Creation resolves the destination's regulatory profile from the product-and-state pairing and stores it as `profile_id`; the filing's `state_code` must equal the resolved profile's state. If no profile exists for the pairing the create is rejected with `ERR_NOT_FOUND`; if the profile exists but is not `ACTIVE` the rejection is `ERR_PROFILE_INACTIVE`. The referenced indication must be `LOCKED` — a draft, in-review, approved-but-unlocked, or superseded indication draws `ERR_INDICATION_NOT_LOCKED` — and no further affinity between the indication and the filing's product or state is enforced. Creation imposes no temporal check on `proposed_effective_date`; the lead-time rule is enforced only at submission. Two structural guards complete creation: at most one filing may be open per product and state, where open means `DRAFT`, `READY`, `SUBMITTED`, `UNDER_OBJECTION`, `APPROVED`, or `DEEMED_APPROVED` (an `EFFECTIVE` filing does not block its successor), and a conflicting open filing triggers `ERR_DUPLICATE_OPEN_FILING` (HTTP 409); and the proposed change may not exceed the state's ceiling, so a `proposed_change_pct` above the profile's `max_single_change_pct` is refused with `ERR_CHANGE_EXCEEDS_MAX` (HTTP 422).

The filing's substance lives in its **components**. While the filing is `DRAFT` — and only then; attempts against a filing in any other state are rejected with `ERR_INVALID_STATE` (HTTP 409) — a `FilingAnalyst` adds components, each carrying a `component_type` of `RATE`, `RULE`, or `FORM`, a `name` such as "Base Rate Pages", and a `content_ref` pointing at the authored content artifact. Components are born `DRAFT`, and the analyst finalizes each one, moving it to `FINAL`; finalization likewise requires the parent filing to still be `DRAFT`.

States frequently demand departures from the countrywide standard, captured as **deviations** on the filing. A `FilingAnalyst` proposes one by supplying the `filing_id`, a `deviation_type` of `RATE_FACTOR`, `RULE_TEXT`, or `FORM_TEXT`, the `base_reference` identifying the countrywide standard being deviated from, a `deviation_factor` (a multiplicative factor against countrywide, where 1.00 means no deviation), and a `justification` text. A deviation is born `PROPOSED`, and it may be proposed while the parent filing is `DRAFT`, `READY`, `SUBMITTED`, or `UNDER_OBJECTION`. The regulator adjudicates proposed deviations while the filing is `SUBMITTED` or `UNDER_OBJECTION`, approving them to `APPROVED` or rejecting them to `REJECTED` (a filing in any other state draws `ERR_INVALID_STATE`); the analyst may instead withdraw a `PROPOSED` deviation, moving it to `WITHDRAWN`.

When the package is complete, the analyst marks the filing ready, moving it from `DRAFT` to `READY`. Readiness demands the right finalized content for the filing type: a `RATE_CHANGE` or `RATE_RULE_FORM` filing must contain at least one `FINAL` component of type `RATE`; a `RULE_ONLY` filing at least one `FINAL` `RULE` component; a `FORM_ONLY` filing at least one `FINAL` `FORM` component. A filing short of its required set is refused with `ERR_COMPONENT_INCOMPLETE` (HTTP 409).

Submission itself belongs to the `ComplianceOfficer` and moves the filing from `READY` to `SUBMITTED`. Five gates guard the transition, all evaluated per the ordering of §2.8: the profile must be `ACTIVE` (`ERR_PROFILE_INACTIVE`); the referenced indication must still be `LOCKED` (`ERR_INDICATION_NOT_LOCKED`); every deviation attached to the filing must be in `PROPOSED` or `APPROVED` — a withdrawn or rejected deviation still attached at submit time fails with `ERR_DEVIATION_NOT_USABLE` (HTTP 409); the effective-date lead rule must hold — under `PRIOR_APPROVAL` the `proposed_effective_date` must fall at least `min_effective_lead_days` after the submission date, while under `FILE_AND_USE` or `USE_AND_FILE` it must simply be on or after the submission date, with violations rejected as `ERR_EFFECTIVE_LEAD_VIOLATION` (HTTP 422); and the `proposed_change_pct` is checked once more against the profile's `max_single_change_pct` (`ERR_CHANGE_EXCEEDS_MAX`). A successful submission stamps `submitted_at` with the current logical time, assigns the `filing_number` — the literal prefix FIL, a hyphen, the state code, another hyphen, and a six-digit zero-padded sequence number maintained per state, so the first filing submitted to California is numbered FIL-CA-000001 — computes the `deemer_date` (§3.5), and opens the filing's compliance calendar: a `DEEMER_DATE` entry is created `PENDING` whenever the deemer applies, and an `EFFECTIVE_DATE` entry is created `PENDING` with its `due_date` set to the proposed effective date.

### 3.4. The Objection Cycle: Interrogatories, Responses, and SLA Discipline

Once a filing is with the regulator, the objection cycle begins. A `StateRegulator` raises an objection against a filing that is `SUBMITTED` or `UNDER_OBJECTION` — against any other filing state the attempt is rejected with `ERR_INVALID_STATE` — by supplying the `filing_id` and the interrogatory `question_text`. The objection is born `RAISED` with `raised_at` stamped at the current logical time, its `reopen_count` beginning at zero and its `late_breach` beginning false, and its answer deadline `due_at` is computed as `raised_at` plus the profile's `objection_response_sla_days`, applied as whole days. The first objection against a `SUBMITTED` filing moves that filing to `UNDER_OBJECTION`, and each objection event recomputes the filing's `open_objection_count` — the count of its objections in `RAISED`, `RESPONSE_DRAFTED`, `RESPONSE_SUBMITTED`, `OVERDUE`, or `REOPENED`. Raising an objection also opens an `OBJECTION_RESPONSE_DUE` calendar entry in `PENDING`, tracking the exact `due_at` instant.

Answering is a two-hand workflow. A `FilingAnalyst` drafts a response by submitting `response_text` together with `expected_objection_version`, the OCC guard of §2.7: if the objection's `version` has advanced past the client's observation, the draft is rejected with `ERR_STALE_VERSION` (HTTP 412). Drafting is possible from `RAISED`, from `REOPENED`, from `OVERDUE`, and while an earlier draft is still pending (`RESPONSE_DRAFTED`); each draft creates an ObjectionResponse in `DRAFT` status, records the analyst as `drafted_by_user_id`, supersedes any prior `DRAFT` response on the same objection (that response moves to `SUPERSEDED`), moves the objection itself to `RESPONSE_DRAFTED`, and increments the objection's `version` by one. An objection that went `OVERDUE` before being answered keeps its `late_breach` flag true — lateness, once incurred, is permanent.

A `ComplianceOfficer` then submits the current draft to the regulator. The submission requires the response to be the objection's live `DRAFT` (an objection not in `RESPONSE_DRAFTED` rejects the submission with `ERR_INVALID_STATE`); on success the response becomes `SUBMITTED` with `submitted_at` stamped, and the objection moves to `RESPONSE_SUBMITTED`. Timeliness is judged at the deadline with equality counting as on time: a response submitted at or before `due_at` resolves the `OBJECTION_RESPONSE_DUE` calendar entry to `MET`, while a response submitted after `due_at` sets the objection's `late_breach` to true. Meanwhile the clock sweep watches silence: an objection still in `RAISED` or `RESPONSE_DRAFTED` when the logical clock passes `due_at` becomes `OVERDUE`, its `late_breach` is set true, and its calendar entry becomes `MISSED`.

The regulator closes the loop. Resolving a `RESPONSE_SUBMITTED` objection moves it to the terminal state `RESOLVED` with `resolved_at` stamped. Reopening — allowed repeatedly, making the objection lifecycle cyclic — moves a `RESPONSE_SUBMITTED` objection to `REOPENED`, increments `reopen_count` by one, restarts the service clock by recomputing `due_at` as the reopen time plus `objection_response_sla_days`, opens a fresh `PENDING` `OBJECTION_RESPONSE_DUE` entry, and pulls the filing back to `UNDER_OBJECTION` with `open_objection_count` recomputed. The regulator may also withdraw an objection from any non-terminal state — `RAISED`, `RESPONSE_DRAFTED`, `RESPONSE_SUBMITTED`, `OVERDUE`, or `REOPENED` — moving it to `WITHDRAWN` with `resolved_at` stamped; withdrawal supersedes any pending `DRAFT` response, waives the still-`PENDING` `OBJECTION_RESPONSE_DUE` entry, and recomputes the filing's open count.

One subtlety governs the filing's own state through all of this. A filing returns from `UNDER_OBJECTION` to `SUBMITTED` — bubbling up automatically — as soon as none of its objections remains in `RAISED`, `RESPONSE_DRAFTED`, `OVERDUE`, or `REOPENED`. An objection in `RESPONSE_SUBMITTED` therefore does not hold the filing in `UNDER_OBJECTION`; yet note the deliberate asymmetry that `RESPONSE_SUBMITTED` still counts toward `open_objection_count`, so the filing cannot be approved until every objection is fully `RESOLVED` or `WITHDRAWN` (§3.5).

### 3.5. Approval, Deemed Approval, and Effective-Date Resolution

A `StateRegulator` approves a `SUBMITTED` filing only when the objection ledger is clean: `open_objection_count` must be zero, meaning every objection is `RESOLVED` or `WITHDRAWN`, and an approval attempted with open objections is rejected with `ERR_OPEN_OBJECTIONS` (HTTP 409). Approval stamps `approved_at` with the current logical time, resolves the filing's `actual_effective_date` (below), marks the `DEEMER_DATE` calendar entry `MET`, and re-anchors the `EFFECTIVE_DATE` entry, replacing its proposed-date `due_date` with the resolved actual effective date and re-establishing the entry as `PENDING` with `resolved_at` cleared (a `WAIVED` entry is never resurrected, per §2.9).

Effective-date resolution depends on the filing method. Under `PRIOR_APPROVAL`, the `actual_effective_date` is the later of the `proposed_effective_date` and the approval date plus `min_effective_lead_days` — the lead time can push effectiveness past the proposal. Under `FILE_AND_USE` and `USE_AND_FILE`, the `actual_effective_date` is exactly the `proposed_effective_date`, regardless of when approval arrives.

Prior-approval states add a second path: the deemer. When the profile's filing method is `PRIOR_APPROVAL` and its `deemer_days` is greater than zero, submission computes `deemer_date` as the calendar date of `submitted_at` plus `deemer_days`; otherwise — including for a `FILE_AND_USE` or `USE_AND_FILE` profile whose `deemer_days` happens to be positive — `deemer_date` stays null and no deemer machinery applies. During each clock sweep, a `SUBMITTED` filing whose `deemer_date` has been reached — the rule fires at 00:00:00Z of that date, so reaching the deemer date itself is enough — becomes `DEEMED_APPROVED`, but only while no objection of the filing is non-terminal: the deemer tolls for as long as any objection sits in `RAISED`, `RESPONSE_DRAFTED`, `RESPONSE_SUBMITTED`, `OVERDUE`, or `REOPENED`. A deemed approval stamps `approved_at` as 00:00:00Z of the deemer date, resolves `actual_effective_date` with that deemed approval time standing in for the approval instant, marks the `DEEMER_DATE` entry `MET`, and re-anchors the `EFFECTIVE_DATE` entry exactly as a regulator's approval would.

Taking effect is a separate, deliberate act by a `ComplianceOfficer`, and it is where the rate book of §2.10 is enforced. From `APPROVED` or `DEEMED_APPROVED`, the filing may be marked effective once the current date has reached the `actual_effective_date` — attempting it earlier is rejected with `ERR_EFFECTIVE_DATE_NOT_REACHED` (HTTP 409) — and only if no other `EFFECTIVE` filing for the same product and state has an `actual_effective_date` on or after this filing's, since equality is an overlap rather than a succession (`ERR_RATEBOOK_OVERLAP`). Success moves the filing to `EFFECTIVE`, supersedes the incumbent `EFFECTIVE` filing of the rate book (its `superseded_at_date` becomes the successor's `actual_effective_date`, and at the same moment its `APPROVED` deviations move to `SUPERSEDED` and its `FINAL` components move to `SUPERSEDED`), and marks the `EFFECTIVE_DATE` calendar entry `MET`. Use-and-file states permit a shortcut: a filing whose profile uses `USE_AND_FILE` may be marked effective directly from `SUBMITTED` — against any other filing method the attempt draws `ERR_INVALID_STATE` — once the current date has reached the `proposed_effective_date`, with the same ratebook overlap check; the `actual_effective_date` is then simply the `proposed_effective_date`, the incumbent is superseded as above, and the `EFFECTIVE_DATE` entry is marked `MET`.

### 3.6. Withdrawal, Disapproval, and the Post-Effective Rescission Cascade

The insurer may abandon a filing at almost any point: a `FilingAnalyst` or `ComplianceOfficer` may withdraw a filing from `DRAFT`, `READY`, `SUBMITTED`, `UNDER_OBJECTION`, `APPROVED`, or `DEEMED_APPROVED` — an `EFFECTIVE` filing is beyond insurer withdrawal and can leave the rate book only through supersession or post-effective disapproval. Withdrawal cascades through everything the filing touched, with the cascade shaped by how far the filing had progressed. From `DRAFT` or `READY`, its `DRAFT` and `FINAL` components move to `WITHDRAWN` and its `PROPOSED` deviations move to `WITHDRAWN`. From `SUBMITTED`, the same component and proposed-deviation withdrawals occur, any `APPROVED` deviations move to `SUPERSEDED` rather than `WITHDRAWN`, and the filing's `DEEMER_DATE` and `EFFECTIVE_DATE` calendar entries are waived. From `APPROVED` or `DEEMED_APPROVED` — the insurer electing not to implement an approved change — components move to `WITHDRAWN`, `PROPOSED` deviations to `WITHDRAWN`, `APPROVED` deviations to `SUPERSEDED`, and the `EFFECTIVE_DATE` entry is waived. From `UNDER_OBJECTION`, all of the submitted-state cascades apply and, in addition, every non-terminal objection is moved to `WITHDRAWN` with its `resolved_at` stamped and its still-pending calendar entry waived. In every case the filing ends in the terminal `WITHDRAWN` state.

The regulator's negative instrument is disapproval, and it works both before and after effectiveness; it is available only from `SUBMITTED`, `UNDER_OBJECTION`, or `EFFECTIVE`, and an attempt against a filing in any other state is rejected with `ERR_INVALID_STATE` (HTTP 409). Against a `SUBMITTED` filing, disapproval moves it to `DISAPPROVED` and waives its `DEEMER_DATE` and `EFFECTIVE_DATE` calendar entries. Against an `UNDER_OBJECTION` filing, disapproval additionally withdraws every non-terminal objection (stamping `resolved_at`) and waives their `OBJECTION_RESPONSE_DUE` entries alongside the deemer and effective-date entries.

Disapproval after effectiveness — the regulator revoking a filing whose rates are already in use — is deliberately constrained and deliberately destructive. It is available only where the filing method permits post-effective review: the profile's `filing_method` must be `FILE_AND_USE` or `USE_AND_FILE`, and an attempt against a `PRIOR_APPROVAL` filing is rejected with `ERR_INVALID_STATE`. The regulator must act within the statutory window: the current date may be no later than `disapproval_window_days` after the filing's `actual_effective_date`, or the attempt is rejected with `ERR_DISAPPROVAL_WINDOW_CLOSED` (HTTP 409). And the book must still be reversible: if any implementation wave of the filing has reached `COMPLETED`, the disapproval is blocked with `ERR_WAVE_NOT_REVERSIBLE` (HTTP 409). When all three gates pass, the filing moves to `DISAPPROVED` and a three-hop cascade unwinds its footprint. First, every implementation wave of the filing in `RELEASED` moves to `REVERSED`, and every wave still `SCHEDULED` moves to `CANCELLED`. Second, each reversed wave restores its policies: policies in `RATED` return to `PENDING` with their premium computation fields and `wave_id` nulled, while policies in `NOTICE_SENT` or `COMPLETED` move to `RESCINDED` with `current_premium_cents` restored to the snapshotted `baseline_premium_cents`. Third, the calendar is cleaned: the restored policies' still-pending `RENEWAL_NOTICE_DUE` entries are waived, each reversed wave's `WAVE_WINDOW` entry is waived, and each reversed wave's `rated_policy_count` is recomputed to zero. Finally, the filing's `FINAL` components and `APPROVED` deviations move to `SUPERSEDED`, closing the record.

### 3.7. Implementation Waves and the Renewal Book

Approval changes rates on paper; implementation waves change them on policies. The raw material is the renewal book: an `ImplementationLead` onboards each renewing policy with its `product_id`, situs `state_code`, a `policy_number` unique within that product and state — a duplicate is rejected as `ERR_INVALID_REQUEST` (HTTP 400) — the in-force annual `current_premium_cents` (a positive integer), a `class_rel_factor` expressing the policy's class relativity against the book average (1.0 meaning average, validated as a positive decimal), and the upcoming `renewal_effective_date`. Policies are born `PENDING`, unattached to any wave (`wave_id` null).

An `ImplementationLead` schedules a wave against a filing that is `APPROVED`, `DEEMED_APPROVED`, or `EFFECTIVE` — any other filing state draws `ERR_INVALID_STATE` — by supplying the `filing_id`, an inclusive window from `wave_start_date` through `wave_end_date`, and a per-policy disruption `cap_pct`. Scheduling validates the window's shape (an end before the start is rejected with `ERR_WAVE_WINDOW_INVALID`, HTTP 422) and its separation from the rest of the rate book's calendar: considering only existing waves of the same product and state in `SCHEDULED`, `RELEASED`, or `COMPLETED` — `CANCELLED` and `REVERSED` waves impose no constraint — the new window must either begin more than seven days after the existing wave's end or end more than seven days before the existing wave's start; a separation of exactly seven days is a violation, while eight days is acceptable, and a breach is rejected with `ERR_WAVE_GAP_VIOLATION` (HTTP 409). The disruption cap faces the state's ceiling: a `cap_pct` above the profile's `max_single_change_pct` is refused with `ERR_CAP_ABOVE_REGULATORY_MAX` (HTTP 422). Scheduling also requires the destination state's profile to be `ACTIVE`; a suspended profile blocks wave scheduling with `ERR_PROFILE_INACTIVE`, just as it blocks filing creation and submission. A wave is created in `SCHEDULED` status with `product_id` and `state_code` denormalized from its filing and `approved_change_pct` snapshotted from the filing's `proposed_change_pct` at creation; the computed `balance_factor`, `target_book_delta_cents`, and `final_book_delta_cents` remain null until release, and the counters `rated_policy_count` and `excluded_late_notice_count` begin at zero. Creation also opens a `WAVE_WINDOW` calendar entry in `PENDING`, due at the end of the wave's last day. The lead may cancel a scheduled wave, moving it to `CANCELLED` and waiving its window entry.

Release is the atomic heart of implementation and is permitted only once the parent filing is `EFFECTIVE` — an attempt against a filing in any other state is rejected with `ERR_INVALID_STATE`. On release, the wave claims its scope: every `PENDING` policy of the same product and state whose `renewal_effective_date` falls within the wave window, both bounds inclusive, comes in scope. Timely notice is then tested per policy against `notice_due_date`, computed as the `renewal_effective_date` minus the profile's `renewal_notice_days`: if the release date is already past a policy's `notice_due_date`, timely notice is impossible by construction, so the policy stays `PENDING`, its `exclusion_reason` is set to `LATE_NOTICE_BY_CONSTRUCTION`, and the wave's `excluded_late_notice_count` increments. Each remaining in-scope policy moves to `RATED` in one motion: `baseline_premium_cents` snapshots the `current_premium_cents`, the policy is re-rated (below), its `wave_id` is set, and a `RENEWAL_NOTICE_DUE` calendar entry opens in `PENDING` for the policy's notice due date.

Re-rating applies the approved change through the policy's relativity and then the disruption cap. The raw change is `approved_change_pct` multiplied by the policy's `class_rel_factor`, rounded to four decimal places half up and stored as `raw_change_pct`; the uncapped new premium `raw_new_premium_cents` is `current_premium_cents` multiplied by one plus `raw_change_pct`, rounded half up to a whole cent. Capping triggers only on strict inequality: when `raw_change_pct` is strictly greater than the wave's `cap_pct`, the capped premium becomes `current_premium_cents` multiplied by one plus `cap_pct`, rounded half up to a whole cent, and `was_capped` is set true; when `raw_change_pct` is strictly below negative `cap_pct`, the capped premium becomes `current_premium_cents` multiplied by one minus `cap_pct` with the same rounding, and `was_capped` is again true; otherwise the capped premium is the raw premium and `was_capped` is false. A raw change exactly equal to the cap, in either direction, is not capped.

Book-level balancing then runs in a pinned order, because the per-policy caps generally pull the book away from the approved change. With every capped premium known, the wave's `target_book_delta_cents` is computed as `approved_change_pct` multiplied by the sum of `baseline_premium_cents` across the rated set, rounded half up to a whole cent. The capped book total is formed as the sum of baselines plus the sum of each policy's capped premium minus its baseline. The `balance_factor` is then the sum of baselines plus `target_book_delta_cents`, divided by that capped book total, stored at eight decimal places rounded half up. Each policy's `final_premium_cents` is its capped premium multiplied by `balance_factor`, rounded half up to a whole cent. Finally, the residual — `target_book_delta_cents` minus the sum over the rated set of each policy's `final_premium_cents` minus its baseline — is allocated in full, sign included, to the single policy holding the largest `baseline_premium_cents`, with ties broken in favor of the policy created earliest; after this allocation the sum of per-policy deltas equals `target_book_delta_cents` exactly, and that realized sum is recorded as `final_book_delta_cents`. The wave's `rated_policy_count` — the count of its policies in `RATED`, `NOTICE_SENT`, or `COMPLETED` — and both book deltas are recomputed at release. Should a release find no in-scope policies at all, the `balance_factor` stays null and both book deltas record zero; the release still succeeds and the wave stands `RELEASED`.

From there, notice discipline governs each policy. Sending the policyholder notice moves a `RATED` policy to `NOTICE_SENT`, stamps `notice_sent_at`, and marks its `RENEWAL_NOTICE_DUE` entry `MET` — but only while the notice is timely, meaning the sending date is on or before the `notice_due_date`; a late attempt is rejected with `ERR_NOTICE_DEADLINE_PASSED` (HTTP 409). Binding completes the renewal: once the current date has reached the `renewal_effective_date` (earlier attempts draw `ERR_EFFECTIVE_DATE_NOT_REACHED`), completing the renewal moves the policy from `NOTICE_SENT` to `COMPLETED` and the new rate binds as `current_premium_cents` takes the value of `final_premium_cents`. Policies that fall through the cracks are swept: a policy still `RATED` when the logical clock passes its `renewal_effective_date` without a notice ever sent — a renewal that has passed unactionable — is bounced back to `PENDING` with `wave_id`, `baseline_premium_cents`, `raw_change_pct`, `raw_new_premium_cents`, `was_capped`, `final_premium_cents`, and `notice_due_date` all nulled, its `exclusion_reason` set to `LATE_NOTICE_SWEEP`, its `RENEWAL_NOTICE_DUE` entry marked `MISSED`, and its wave's `rated_policy_count` recomputed; in practice the bounce fires as soon as a `RATED` policy's `notice_due_date` has passed, the notice deadline itself being the last moment the renewal remained actionable. A wave whose end date has passed with no policies left in `RATED` or `NOTICE_SENT` — every assigned policy `COMPLETED` or `RESCINDED` — is swept to `COMPLETED`, and its `WAVE_WINDOW` entry is marked `MET`.

Reversal is the compensating instrument, available to the lead from `RELEASED` and also invoked systemically by the post-effective disapproval cascade of §3.6. Reversing a wave moves it to the terminal `REVERSED` state: its `RATED` policies return to `PENDING` with `wave_id`, `baseline_premium_cents`, `raw_change_pct`, `raw_new_premium_cents`, `was_capped`, `final_premium_cents`, and `notice_due_date` all nulled; its `NOTICE_SENT` and `COMPLETED` policies move to `RESCINDED` — the terminal state of the policy lifecycle — with `current_premium_cents` restored to the `baseline_premium_cents` snapshot and the same computation fields (`baseline_premium_cents`, `raw_change_pct`, `raw_new_premium_cents`, `was_capped`, `final_premium_cents`, `notice_due_date`) nulled, though `wave_id` and `notice_sent_at` are retained for audit; the affected policies' pending `RENEWAL_NOTICE_DUE` entries and the wave's `WAVE_WINDOW` entry are waived; and `rated_policy_count` recomputes to zero. Rescission after binding is precisely the compensating action that restores the baseline premium ledger.

For oversight, the API computes a disruption analysis over a wave's policies in `RATED`, `NOTICE_SENT`, or `COMPLETED`: `total_policies` counts them; `capped_policy_count` counts those with `was_capped` true; `max_raw_change_pct` and `min_raw_change_pct` report the extreme `raw_change_pct` values; `book_avg_raw_change_pct` is the sum of each policy's `raw_new_premium_cents` minus its baseline, divided by the sum of baselines, rounded to four decimal places half up; `book_avg_final_change_pct` repeats that ratio using `final_premium_cents`; and the summary carries the wave's `balance_factor`, `target_book_delta_cents`, and `final_book_delta_cents` alongside. A wave with no rated policies reports zero counts and null averages and extrema.

## 4. Endpoint Definitions

Operations that create a new resource — a product, profile, indication, filing, component, deviation, objection, objection response draft, wave, or policy — return a `201 Created` status code. Operations that modify or transition an existing resource, and the logical-clock capability, return a `200 OK` status code. Successful responses return the affected resource in the envelope of §2.2. The request and response payloads of each operation are defined by the workflows of §3; this table is the index of HTTP contracts and authorized roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock and trigger the system sweep | PlatformAdmin |
| POST | `/products` | Create a Product | ProductActuary |
| GET | `/products/{productId}` | Get a Product | All roles |
| POST | `/state-profiles` | Create a StateRegulatoryProfile for a product and state | ComplianceOfficer |
| GET | `/state-profiles/{profileId}` | Get a StateRegulatoryProfile | All roles |
| GET | `/state-profiles` | List StateRegulatoryProfiles | All roles |
| POST | `/state-profiles/{profileId}/suspend` | Suspend a profile, blocking new filings | ComplianceOfficer |
| POST | `/state-profiles/{profileId}/reactivate` | Reactivate a suspended profile | ComplianceOfficer |
| POST | `/rate-indications` | Create a RateIndication; both calculation variants computed at creation | ProductActuary |
| GET | `/rate-indications/{indicationId}` | Get a RateIndication | All roles |
| GET | `/rate-indications` | List RateIndications | All roles |
| POST | `/rate-indications/{indicationId}/submit-review` | Submit an indication for actuarial review | ProductActuary |
| POST | `/rate-indications/{indicationId}/approve` | Approve an indication (segregation of duties enforced) | ProductActuary |
| POST | `/rate-indications/{indicationId}/return` | Return an indication to draft for revision | ProductActuary |
| POST | `/rate-indications/{indicationId}/lock` | Lock an approved indication, superseding the prior locked indication of the same scope | ProductActuary |
| POST | `/filings` | Create a RateFiling; the state profile is resolved from the product and state | FilingAnalyst |
| GET | `/filings/{filingId}` | Get a RateFiling | All roles |
| GET | `/filings` | List RateFilings | All roles |
| POST | `/filings/{filingId}/mark-ready` | Move a filing from draft to ready after the component completeness check | FilingAnalyst |
| POST | `/filings/{filingId}/submit` | Submit a filing to the state regulator | ComplianceOfficer |
| POST | `/filings/{filingId}/withdraw` | Withdraw a non-terminal filing | FilingAnalyst, ComplianceOfficer |
| POST | `/filings/{filingId}/approve` | Regulator approves a submitted filing | StateRegulator |
| POST | `/filings/{filingId}/disapprove` | Regulator disapproves a filing, pre- or post-effective | StateRegulator |
| POST | `/filings/{filingId}/mark-effective` | Move an approved filing into effect, superseding the incumbent ratebook filing | ComplianceOfficer |
| POST | `/filings/{filingId}/components` | Add a component to a draft filing | FilingAnalyst |
| GET | `/components/{componentId}` | Get a FilingComponent | All roles |
| GET | `/components` | List FilingComponents | All roles |
| POST | `/components/{componentId}/finalize` | Finalize a component | FilingAnalyst |
| POST | `/deviations` | Propose a state-specific deviation on a filing | FilingAnalyst |
| GET | `/deviations/{deviationId}` | Get a Deviation | All roles |
| GET | `/deviations` | List Deviations | All roles |
| POST | `/deviations/{deviationId}/approve` | Regulator approves a deviation | StateRegulator |
| POST | `/deviations/{deviationId}/reject` | Regulator rejects a deviation | StateRegulator |
| POST | `/deviations/{deviationId}/withdraw` | Withdraw a proposed deviation | FilingAnalyst |
| POST | `/objections` | Regulator raises an objection against a submitted filing | StateRegulator |
| GET | `/objections/{objectionId}` | Get an Objection | All roles |
| GET | `/objections` | List Objections | All roles |
| POST | `/objections/{objectionId}/responses` | Draft a response to an objection (OCC-guarded; supersedes any existing draft) | FilingAnalyst |
| GET | `/responses/{responseId}` | Get an ObjectionResponse | All roles |
| GET | `/responses` | List ObjectionResponses | All roles |
| POST | `/responses/{responseId}/submit` | Submit the drafted response to the regulator | ComplianceOfficer |
| POST | `/objections/{objectionId}/resolve` | Regulator resolves an objection | StateRegulator |
| POST | `/objections/{objectionId}/reopen` | Regulator reopens a submitted objection with a fresh SLA clock | StateRegulator |
| POST | `/objections/{objectionId}/withdraw` | Regulator withdraws an objection | StateRegulator |
| POST | `/waves` | Schedule an implementation wave for an approved filing | ImplementationLead |
| GET | `/waves/{waveId}` | Get an ImplementationWave | All roles |
| GET | `/waves` | List ImplementationWaves | All roles |
| POST | `/waves/{waveId}/release` | Release a scheduled wave, assigning and rating in-scope renewal policies atomically | ImplementationLead |
| POST | `/waves/{waveId}/reverse` | Reverse a released wave with full premium restoration | ImplementationLead |
| POST | `/waves/{waveId}/cancel` | Cancel a scheduled wave | ImplementationLead |
| GET | `/waves/{waveId}/disruption-analysis` | Computed disruption summary of a wave | All roles |
| POST | `/policies` | Onboard a renewal policy into the book | ImplementationLead |
| GET | `/policies/{policyId}` | Get a RenewalPolicy | All roles |
| GET | `/policies` | List RenewalPolicies | All roles |
| POST | `/policies/{policyId}/send-notice` | Send the policyholder renewal notice | ImplementationLead |
| POST | `/policies/{policyId}/complete-renewal` | Bind the renewal at its effective date | ImplementationLead |
| GET | `/calendar-entries/{entryId}` | Get a ComplianceCalendarEntry | All roles |
| GET | `/calendar-entries` | List ComplianceCalendarEntries | All roles |
| POST | `/calendar-entries/{entryId}/waive` | Waive a pending calendar obligation | ComplianceOfficer |

## 5. Error Code Catalogue

The trigger condition for each error is specified in the narratives of §2 and §3; this catalogue is the index of identifiers and their HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_PROFILE_INACTIVE` | 409 Conflict |
| `ERR_INDICATION_NOT_LOCKED` | 409 Conflict |
| `ERR_DEVIATION_NOT_USABLE` | 409 Conflict |
| `ERR_COMPONENT_INCOMPLETE` | 409 Conflict |
| `ERR_DUPLICATE_PROFILE` | 409 Conflict |
| `ERR_DUPLICATE_OPEN_FILING` | 409 Conflict |
| `ERR_OPEN_OBJECTIONS` | 409 Conflict |
| `ERR_RATEBOOK_OVERLAP` | 409 Conflict |
| `ERR_WAVE_GAP_VIOLATION` | 409 Conflict |
| `ERR_WAVE_NOT_REVERSIBLE` | 409 Conflict |
| `ERR_EFFECTIVE_LEAD_VIOLATION` | 422 Unprocessable Content |
| `ERR_EFFECTIVE_DATE_NOT_REACHED` | 409 Conflict |
| `ERR_DISAPPROVAL_WINDOW_CLOSED` | 409 Conflict |
| `ERR_NOTICE_DEADLINE_PASSED` | 409 Conflict |
| `ERR_WAVE_WINDOW_INVALID` | 422 Unprocessable Content |
| `ERR_CHANGE_EXCEEDS_MAX` | 422 Unprocessable Content |
| `ERR_CAP_ABOVE_REGULATORY_MAX` | 422 Unprocessable Content |






