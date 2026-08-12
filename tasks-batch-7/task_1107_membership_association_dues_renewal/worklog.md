# Worklog — task_1107_membership_association_dues_renewal

## Step 1: Create Task Directory — 2026-08-10T15:16:24.420Z

Pre-assigned output folder `tasks/task_1107_membership_association_dues_renewal` with `workspace/` subdirectory already exists (auto-index scan skipped per orchestration directive). Step 1 treated as done.

## Step 2: Generate Scaffold — 2026-08-10T15:34:00.000Z

## Summary

**Files written (all three verified valid YAML, correct top-level structure, lint-clean):**

| File | Size | Top-level key(s) |
|---|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_1107_membership_association_dues_renewal/SCAFFOLD.yaml` | 56,558 B | `scenario`, `domain_name`, `api_prefix`, `complexity_profile`, `entities`, `state_machines`, `concurrency_rules`, `calculations`, `validations`, `response_envelope`, `endpoints`, `errors`, `roles` (no §1.8/§1.9 keys) |
| `/home/ubuntu/github/CodingPRD/tasks/task_1107_membership_association_dues_renewal/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 70,979 B | single key `scaffold_difficulty_design` |
| `/home/ubuntu/github/CodingPRD/tasks/task_1107_membership_association_dues_renewal/SCAFFOLD_CORNER_DESIGN.yaml` | 60,006 B | single key `scaffold_corner_design` |

**Coverage:**
- Entities: 14 (MembershipCategory, DuesSchedule, Chapter, RenewalCyclePolicy, Member, MembershipTerm, DuesInvoice, PaymentAttempt, AutoRenewAuthorization, BenefitEntitlement, DirectoryListing, DuesIncreaseNotice, RevenueAttribution, ReinstatementRequest)
- Endpoints: 42 (including 2 test-driving: `/api/_clock/set_current_utc` with startup default `2026-05-01T00:00:00Z`, `/api/_scheduler/run_renewal_cycle`)
- Errors: 20
- Calculations: 7 (including two dual-variant domains: dues_invoice_amount anniversary vs calendar_prorated; chapter_share vs non_dues_revenue_attribution)
- Validations: 16 priorities
- Concurrency rules: 2 (OCC on Member.version for resign and auto-renew-revoke)
- §1.8 instances: 18 (exactly 2 per rule × 9 rules)
- §1.9 instances: 26 (23 active + 3 excluded stubs citing §1.8 instances)

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Key design decisions adjudicated:**
- **Primary archetype:** pricing_engine (tiered dues schedule, proration, dues increase) with secondary compliance_audit (grace period, reinstatement windows). Complexity layers: optimistic concurrency, cascading side effects, dual-variant calculation, scheduled actions.
- **Difficulty anchoring:** proration variants produce literal `120000` (anniversary) vs `80219` (calendar, 244 days / 365); chapter share with `bps=3333` on `120001` produces `39996` to pin the rounding order; risk score arithmetic pre-computed (`40+22+25=87`).
- **Parallel state dimensions** on `DuesInvoice` (payment_status × fulfillment_status) satisfies Rule 3 without reusing the cyclic Member machine.
- **Two distinct temporal-overlap semantics** for Rule 8: half-open `[from, to)` interval collision on DuesSchedule, vs. gap-detection and back-dues pricing on MembershipTerm reinstatement.
- **Two compensating invariants:** `Member.lifetime_dues_paid_cents` (cents) and `count(BenefitEntitlement)` (row count) — different conserved quantities.
- **RBAC model:** hierarchical_override with three roles (Member entity_backed; MembershipAdministrator + DuesAdministrator opaque). DuesAdministrator has no refund privilege (segregation-of-duties flavour).
- **Lint-driven §1.5 additions** (FK reverse-reachability): added `cycle_policy_id?` to `GET /api/members`, added flat `GET /api/dues-invoices` with `membership_term_id?`/`dues_schedule_id?`, added sub-resource `GET /api/dues-invoices/{id}/reinstatement-requests`.

## Step 3: Copy Shared Files — 2026-08-10T15:34:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `tasks/task_1107_membership_association_dues_renewal/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-10T15:41:00.000Z

## Summary

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_1107_membership_association_dues_renewal/workspace/PRD.md`
**Size**: 43,321 bytes, 279 lines

### Section Outline
- **§1. Introduction** (3 paragraphs — system goals, three operational burdens, PRD scope)
- **§2. Global Specifications & System-Wide Principles** — 9 subsections:
  - 2.1 User and Role-Based Access Control (headers, 3 roles with identity translation)
  - 2.2 API Response Structure (verbatim from `section-2.2-response-structure.md`)
  - 2.3 Pagination (limit/offset defaults, min/max, sort order)
  - 2.4 Common Resource Properties (id UUID, created_at/updated_at, version)
  - 2.5 Validation Order and Error Surface (priority 1–16 spelled out)
  - 2.6 Hierarchical Path Validation (left-to-right)
  - 2.7 Monetary Precision and Rounding (integer cents, round half up)
  - 2.8 Optimistic Concurrency Control on Member Mutations (both OCC rules)
  - 2.9 Logical Clock and Test-Driving Endpoints (startup default `2026-05-01T00:00:00Z`)
- **§3. Business Logic & Workflows** — 10 subsections organized by domain lifecycle:
  - 3.1 Reference Data; 3.2 Dues Schedules & Increase-Notice Contract; 3.3 Member Registration; 3.4 Pricing the Dues Invoice (ANNIVERSARY vs CALENDAR variants); 3.5 Capturing Payment (settle/transient/hard-decline/refund paths); 3.6 Verification Cascade; 3.7 Member Lifecycle (grace, lapse, reinstatement, resignation, expulsion); 3.8 Auto-Renewal Consent and Scheduler; 3.9 Risk Score, Benefits, Directory; 3.10 Non-Dues Revenue Attribution
- **§4. Endpoint Definitions** — 42-row table (Method, Path, Description, Authorized Roles)
- **§5. Error Code Catalogue** — 20-row table (Error ID, HTTP Status Code)

### Coverage Audit (all PASS)

**Contract 1 — Field-Name Coverage**: 75 required fields, 75 present, 0 missing. Includes every `entities[].fields[].name`, every `endpoints[].input`/`query_params`/`path_params`, plus `id`/`created_at`/`updated_at`/`version`.

**Contract 2 — Rule Coverage**:
- validations[] with priority: 16/16 expressed in §2.5 ordered prose
- concurrency_rules[] OCC rejections: 2/2 (resign + auto-renew revoke, both with `expected_member_version`, `ERR_STALE_VERSION`, HTTP 412)
- state_machines[].transitions: 22/22 transitions expressed with from/to states named
- calculations[]: 7/7 expressed in prose (dues_invoice_amount, chapter_share_amount, dues_increase_notice_gap, member_risk_score, non_dues_revenue_attribution, reinstatement_back_dues, benefit_suspension_propagation) — no pseudocode, all formulas translatable step-for-step
- validations[] conditions: 16/16 matchable to error_id in prose
- endpoints[].side_effects / applies_to: all expressed in §3 narratives
- entities[].fields[] structured content: all reconstructible (types, defaults, initial values, enum memberships named)
- sibling-branch symmetry: verified for ANNIVERSARY/CALENDAR variants, PRO_RATA_DAILY/FULL_PERIOD/NONE proration branches, SUCCEEDED/DECLINED_TRANSIENT/DECLINED_HARD payment outcomes, approve/reject/expire reinstatement branches, resign/expel cascades

**Contract 3 — §3 Path Purity**: 516 backtick tokens scanned in §3; 0 tokens starting with `/`; 0 bare HTTP-method tokens; 0 method+path combined tokens. All endpoints referenced via state-transition framing, role + action verb, or capability description.

**All 20 error codes** appear in PRD prose (§2 or §3) with their trigger conditions; §5 contains the 2-column reference table.

### Zero-Silence Adjudications

1. **`PENDING_VERIFICATION` initial-invoice settle vs `ERR_MEMBER_NOT_GRACE`**: The scaffold specifies both that the initial invoice must settle before verification AND that renewal payments require the member to be in `ACTIVE` or `GRACE`. I added a clarifying sentence in §3.5 noting the guard does not block the initial-invoice settle (which is part of the verification flow); this is the only coherent reading and I called it out explicitly so the implementer does not double-guess.

2. **`due_at` for joins vs renewals**: Scaffold says `due_at` equals `period_end` for renewals. For the initial join invoice, I extended the rule naturally — "and to the period end of the opening term for joins" — since the scaffold's `due_at` description does not carve out a separate rule for the join invoice and the implementer needs a determinate answer.

3. **`DirectoryListing` defaults at verification**: Scaffold side-effect says "Creates DirectoryListing with visibility_state = VISIBLE if category.is_directory_eligible AND is_public=true, else HIDDEN_OPT_OUT or HIDDEN_CATEGORY" but `is_public` is an input field with no explicit initial value. I adjudicated that `display_name` defaults from `full_name`, `specialty_tags` starts empty, and `is_public` defaults to false (opt-in flag) — the visibility_state computation then flows from those defaults.

4. **Back-dues invoice `due_at`**: The scaffold does not specify a special `due_at` rule for the back-dues invoice created on reinstatement. I left it implicit under the standard issuance rule; the implementer can default to the invoice's covered period end.

5. **Clock endpoint behavior pre-set**: Explicitly enforced the startup default `2026-05-01T00:00:00Z` and the "no wall-clock fallback before any set_current_utc call" rule in §2.9 (mirroring the endpoint description verbatim).

## Step 5: Generate Unit Tests — 2026-08-10T15:55:00.000Z

All required files present, all compile. Generation complete.

---

## Summary

### Files written

**`/home/ubuntu/github/CodingPRD/tasks/task_1107_membership_association_dues_renewal/test_helpers/`** (9 files, 37 KB)
- `__init__.py` (1028 B) — barrel export
- `types.py` (6922 B) — TypedDicts + status enums for 14 entities + role enum
- `api_client.py` (7828 B) — `ApiClient(GenericApiClient)` with 32 endpoint methods covering every endpoint in PRD §4
- `api_errors.py` (2280 B) — 20 error IDs + HTTP map registered via `set_error_http_status_map`
- `assertions.py` (7698 B) — per-entity `assert_<entity>()` validators
- `factories.py` (2215 B) — payload factories for input-bearing entities
- `constants.py` (515 B) — proration/leap/bps/retry-cap/risk-cap constants
- `test_users.py` (1245 B) — `TEST_USERS` shared constants + `make_member_headers(member_id)` builder (mandatory for entity_backed Member)
- `fixtures.py` (8443 B) — composite helpers: reference-data bundle, member registration, settle/verify, scheduler/clock drivers, pending-renewal fetch, benefit/directory/auto-renew readers

**`/home/ubuntu/github/CodingPRD/tasks/task_1107_membership_association_dues_renewal/test_suite/`** (6 files, 87 KB)
- `conftest.py` (572 B)
- `test_01_pricing_and_schedule.py` (14 tests) — dual-variant pricing, chapter-share rounding order, increase-notice gap boundary, half-open overlap, publish priority pair, leap-year pro-rata, supersession, DRAFT initial state
- `test_02_member_lifecycle.py` (11 tests) — verify gating, computed-field defaults, not-found, pagination envelope, GRACE↔ACTIVE cycle, reinstatement re-anchor, double-resign, OCC stale-version
- `test_03_invoice_payment_refund.py` (13 tests) — parallel payment×fulfillment axes, refund cascade (member+entitlements), hard-decline cascade (auto-renew suspend+version bump), refund priority pair, lifetime conservation, retry cap, immediate consistency
- `test_04_auto_renew_and_revenue.py` (9 tests) — auto-renew gating, chapter-share vs revenue-attribution divergence, benefit-count conservation, DUES kind rejection, email uniqueness, non-existent reference
- `test_05_rbac_and_cascade.py` (5 tests) — RBAC denials (publish/expel/refund), expel cascade, response envelope shape

**Total: 52 tests.**

### Coverage

**Queue A (Difficulty): 16/18 instances translated (2 skipped)**
- Every translated instance has ≥2 tests tagged `Design: Difficulty/<rule_id>/<name>`
- **SKIPPED:**
  - `combinatorial_formula/member_risk_score_weighted_3_input_formula` — Setup requires `benefit_usage_events_30d = 5`, but the PRD exposes no API to record benefit-usage events. Two PRD-only implementers cannot both satisfy the fixture.
  - `boundary_precision_check/reinstatement_window_zero_days_elapsed` — Asserts filing at exactly `lapse + reinstatement_window_days` is *allowed*. PRD §3.7 is contradictory: the filing rule rejects when "after … have elapsed" (= at boundary) but the approve precondition allows "within reinstatement_window_days" (≤). Not uniquely derivable.

**Queue B (Corner): 20/23 non-stub instances translated (3 skipped, plus 3 `excluded_because:` stubs not translated per rule)**
- **SKIPPED:**
  - `entities/member_creation_required_fields_missing_returns_invalid` — The instance's own assert is a disjunction over four unrelated error IDs; PRD §2.5 does not name a rule for missing required input fields, so no unique outcome.
  - `state_machines/auto_renew_terminal_revoked_cannot_reactivate` — Design asserts `ERR_INVALID_STATE`, but PRD §3.8 uniquely derives `ERR_NO_AUTO_RENEW_ACTIVE` for reactivation outside `SUSPENDED_HARD_DECLINE`. Asserted outcome conflicts with PRD.
  - `endpoints/increase_notice_broadcast_audience_size` — Design asserts `status == SENT`, but PRD §3.2 explicitly sets `status` to `SCHEDULED` at broadcast. Conflict.
- **Stubs correctly not translated** (cross-references verified to resolve in queue A): `member_grace_to_active_on_renewal_settle`, `auto_renew_suspended_on_failed_final`, `chapter_share_calculation_correctness`.

### Stage-gate lint results
- `python3 -m py_compile test_helpers/*.py test_suite/*.py` → **PASS** (all 15 files)
- Docstring tag audit → **16 unique Difficulty tags + 20 unique Corner tags**, all copied verbatim from the source YAML `name:` fields; no untagged or dual-tagged tests.

## Step 6: Generate Implementation — 2026-08-10T15:55:30.000Z

All three verifications pass. Summary:

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_1107_membership_association_dues_renewal/workspace/implementation/`:

| Size (B) | File |
|---|---|
| 263 | `start.sh` (guarded pip install, `exec python3 app.py`, foreground) |
| 11 | `requirements.txt` (flask>=3.0) |
| 1108 | `app.py` (blueprint registration, error handlers, `0.0.0.0:$PORT`) |
| 2734 | `db.py` (in-memory dicts, logical clock defaulting to `2026-05-01T00:00:00Z`, ISO-8601 ms timestamps) |
| 2083 | `errors.py` (full error catalog from SCAFFOLD Table 6) |
| 1031 | `response.py` (envelope: `meta`/`response_type`/`data`, error body `error_id`/`message`) |
| 1141 | `middleware.py` (`X-User-ID`/`X-User-Role` auth, RBAC, ownership checks) |
| 3047 | `routes/reference.py` (categories, chapters, cycle policies) |
| 6767 | `routes/schedules.py` (dues schedules, publish/retire, increase notices) |
| 11270 | `routes/members.py` (register/verify/resign/expel, terms, benefits, directory, revenue) |
| 8097 | `routes/invoices.py` (invoice lists, payments, refund, attempts) |
| 7949 | `routes/lifecycle_ops.py` (auto-renew, reinstatement, clock/scheduler) |
| 4254 | `services/pricing.py` (dues amount, chapter share, notice gap, back-dues walk) |
| 13481 | `services/lifecycle.py` (serializers, risk score, benefit/directory propagation, settle cascade) |
| 6187 | `services/scheduler.py` (renewal sweep: invoice issuance, auto-renew charges, GRACE/LAPSED/EXPELLED/EXPIRED transitions) |

## Verification results

1. **Route-pair diff: zero missing.** 42 declared (method, path) pairs in SCAFFOLD.yaml endpoints table vs 43 registered Flask rules — the only extra is Flask's built-in `/static/<path>` helper. All 42 declared endpoints are registered.
2. **Smoke test: pass.** `PORT=18743 bash start.sh` booted, `POST /api/membership-categories` returned 201 with correct envelope (`meta.api_request_id` with `req_` prefix, `api_request_timestamp` with 3 fractional digits from logical clock, `response_type: "object"`, version 1), unauthenticated GET returned 401 `ERR_UNAUTHENTICATED` in the error envelope. Server killed cleanly.
3. **`python3 -m py_compile`: pass** on all 14 `.py` files.

## PRD-silence adjudications resolved at generation time

- **Chapter share field at issuance:** SCAFFOLD says `chapter_share_cents` is "computed on SETTLED" — returned as `null` until settle, then rounded half-up per `chapter_share_amount` (share computed first, national by subtraction).
- **Risk-score benefit usage:** no endpoint records usage events; `benefit_usage_events` store exists but stays empty, so usage component is 30 unless tests never exercise it. Failed-payment and expiry components fully implemented per formula (caps 40/30/30, clamp 0–100, only for ACTIVE/GRACE/LAPSED).
- **`GET /api/members/{id}/verify` ownership:** Member role restricted to self (`X-User-ID == member id`) per PRD §2.1 ownership rule; admin roles not in the scaffold's role list for that endpoint, so they get 403.
- **Verification entitlement set:** PRD §3.6 lists the five-benefit set with `VOTING_BALLOT` conditional on `is_voting`; implemented literally (other four always granted).
- **Refund with remaining coverage:** `current_period_end` resets to the latest remaining SETTLED term's period_end; only transitions to GRACE when no settled coverage remains (per PRD §3.5).
- **Auto-renew sweep charge:** PRD §3.8 doesn't specify simulated outcomes for sweep-initiated charges; implemented as SUCCEEDED (records PaymentAttempt + settle cascade).
- **404/405 non-API paths:** mapped to the standard error envelope with `ERR_NOT_FOUND`.
- **Storage:** pure in-memory dicts; no seeding, no files, no wall-clock fallback before any `set_current_utc` call.

## Step 7: Run Tests and Iterate — 2026-08-10T16:08:00.000Z

## Summary

**Iterations run:** 3 (sweep 1: 42/52; sweep 2: 49/52; sweep 3: 52/52 across all 8 rounds).

**Tests deleted:** None. All 10 initially failing tests traced to PRD-verbatim rules.

**Fixes applied to `test_helpers/`:** None — failures were all implementation-side.

**Fixes applied to `implementation/`:**

1. **`/home/ubuntu/github/CodingPRD/tasks/task_1107_membership_association_dues_renewal/workspace/implementation/services/scheduler.py` — `run_sweep` (renewal-invoice issuance + auto-renew charge).** Two fixes:
   - Widened the renewal-invoice issuance condition from `now <= cpe <= lookahead` to `cpe <= lookahead`, so a member whose `current_period_end` has just passed (now in GRACE) still gets a renewal invoice issued. PRD §3.7's "Recovery from grace" presupposes a renewal invoice exists for the GRACE member to settle. Fixed 6 tests (`test_grace_to_active_on_renewal_settle`, `test_renewal_settle_opens_new_term_with_renewal_opened_by`, `test_five_default_entitlements_all_active_after_grace_cycle`, and the three cascade tests).
   - Decoupled auto-renew charge from invoice issuance: auto-renew charge now fires only for unpaid invoices that have reached `due_at` and have no prior payment attempts. Previously the auto-charge ran at issuance, immediately settling the renewal invoice and leaving no PENDING invoice for tests to submit DECLINED attempts against. PRD §3.8 lists "issues renewal DuesInvoice" and "performs auto-renew charge attempt" as separate sweep action groups without requiring them to be atomic; deferral to due-date is the natural reading. Fixed `test_hard_decline_moves_invoice_to_failed_final_and_suspends_auto_renew`, `test_failed_final_bumps_member_version`, `test_expel_cascades_to_all_children`.

2. **`/home/ubuntu/github/CodingPRD/tasks/task_1107_membership_association_dues_renewal/workspace/implementation/routes/invoices.py` — `submit_payment` (member-state guard).** Extended the `ERR_MEMBER_NOT_GRACE` carve-out: a LAPSED member may now pay a back-dues invoice referenced by a PENDING reinstatement request. PRD §3.7 makes back-dues SETTLED a hard precondition for reinstatement approve while the member is necessarily LAPSED; PRD §3.5's guard would otherwise make reinstatement unreachable (mirrors the initial-invoice/PENDING_VERIFICATION carve-out PRD §3.5 already names explicitly). Fixed `test_reinstatement_approve_moves_member_to_active`, `test_reinstatement_opens_new_term_with_reinstatement_opened_by`.

3. **`/home/ubuntu/github/CodingPRD/tasks/task_1107_membership_association_dues_renewal/workspace/implementation/routes/schedules.py` — `_check_overlap`.** Skip the `ERR_SCHEDULE_OVERLAP` rejection when the conflicting prior PUBLISHED schedule is open-ended (`effective_to IS NULL`) and starts strictly before the new schedule's `effective_from` — such a prior is the supersession target named in PRD §3.2 ("any previously PUBLISHED schedule for the same category transitions to SUPERSEDED at the new schedule's effective_from"). Bounded priors (explicit `effective_to`) and back-filling new schedules still reject. Fixed `test_gap_exactly_at_threshold_allowed`, `test_gap_one_day_under_threshold_rejected` while preserving `test_one_day_overlap_rejected` and `test_overlapping_interval_publish_rejected_corner`.

**Final state:** all 8 parallel sweep rounds report 52/52 passed.

Orchestrator disk verification: results.1.json … results.8.json all present, each `{passed: 52, failed: 0, total: 52, errors: 0}`.

## Step 8: Finalize PRD — 2026-08-10T16:12:00.000Z

All three edits committed. Final verification of the diff above confirms each edit is inline within the original paragraphs — no new sections, no renames, no restructuring.

---

## Summary

**File stats**
- `/home/ubuntu/github/CodingPRD/tasks/task_1107_membership_association_dues_renewal/workspace/PRD.md`: 279 lines, 43,321 bytes
- `/home/ubuntu/github/CodingPRD/tasks/task_1107_membership_association_dues_renewal/workspace/PRD_FINALIZED.md`: 279 lines, 44,812 bytes
- Line-delta: 0 lines (all edits in-paragraph); byte-delta: +1,491 bytes (+3.4%)

**Changes (one bullet per edit)**

- **§3.8 (Auto-Renewal Consent and the Scheduler)** — revise — Widened renewal-invoice issuance from "every `ACTIVE` member whose `current_period_end` is within the renewal lookahead window" to "every `ACTIVE` or `GRACE` member whose `current_period_end` falls within the renewal lookahead window or has already passed", and pinned that the auto-renew charge is decoupled from issuance — it fires only against an unpaid renewal invoice that has reached `due_at` and has no prior `PaymentAttempt`, so a freshly issued renewal invoice remains `PENDING` (and manually payable) until its due date — `implementation/services/scheduler.py:38-53` (issuance window) and `implementation/services/scheduler.py:59-76` (deferred auto-charge).

- **§3.5 (Capturing Payment — Member-state guard)** — revise — Added a second carve-out alongside the existing `PENDING_VERIFICATION`/initial-invoice one: the `ERR_MEMBER_NOT_GRACE` guard also does not block settling a back-dues invoice for a member in `LAPSED` while that member's `ReinstatementRequest` referencing the invoice as `back_dues_invoice_id` is still `PENDING` — `implementation/routes/invoices.py:113-122`.

- **§3.2 (Dues Schedules and the Increase-Notice Contract)** — revise — Two adjustments: (a) narrowed the overlap rule's trigger from "being created or published" to "being published" (impl runs `_check_overlap` only in `publish_schedule`, never in `create_schedule`); (b) added the supersession carve-out: overlap with a prior `PUBLISHED` schedule that is open-ended and starts strictly earlier than the new schedule's `effective_from` is permitted (that prior is the supersession target), while bounded priors and back-filling publishes still reject — `implementation/routes/schedules.py:24-46` (check) and `implementation/routes/schedules.py:99` (only caller).

**Per-edit pre-edit search log**

- **Edit 1 (§3.8 sweep)**
  - (a) Subject: renewal-invoice issuance condition + auto-renew charge timing in the sweep.
  - (b) Impl paths enumerated: `services/scheduler.py::run_sweep` (lines 38-76), `services/scheduler.py::_auto_renew_charge`, `services/lifecycle.py::settle_invoice`, `services/lifecycle.py::open_term_and_invoice`, both trigger routes `routes/lifecycle_ops.py:201,208`, `routes/invoices.py::submit_payment` (manual path, unaffected), GRACE/LAPSED/EXPELLED transitions at `scheduler.py:79-144`, `db.py:85` (`RENEWAL_LOOKAHEAD_DAYS = 30`, intentionally left unpinned).
  - (c) Wording adjustment: widened subject from "every ACTIVE member" to "every ACTIVE or GRACE member"; added "or has already passed"; inserted a separate sentence pinning that the auto-charge is gated on `due_at` reached and no prior attempts. Avoided naming the lookahead value or the exact trigger order, both unpinned in impl.

- **Edit 2 (§3.5 member-state guard)**
  - (a) Subject: `ERR_MEMBER_NOT_GRACE` guard's carve-outs.
  - (b) Impl paths enumerated: `routes/invoices.py:99-125` (`submit_payment`, the Step 7 site; guard logic at lines 111-125), `routes/lifecycle_ops.py:100-126` (`file_reinstatement` creates the term-less back-dues invoice), `routes/lifecycle_ops.py:140-176` (`approve_reinstatement` requires back-dues SETTLED while member is LAPSED), `services/lifecycle.py::settle_invoice` (cascade agnostic to who submitted), `services/scheduler.py::_auto_renew_charge` (bypasses the guard entirely), reinstatement reject/expire paths (no payment).
  - (c) Wording adjustment: added the second carve-out alongside the existing first one; scoped strictly to "the invoice referenced as `back_dues_invoice_id` on a `PENDING` reinstatement request" (mirrors the impl's `is_back_dues` predicate which requires `membership_term_id is None` AND a PENDING request); explicit "Outside these two carve-outs" guard preservation. Did not extend the carve-out to scheduler auto-charge since impl does not apply the guard there.

- **Edit 3 (§3.2 overlap rule)**
  - (a) Subject: overlap rejection vs supersession carve-out in schedule publish.
  - (b) Impl paths enumerated: `routes/schedules.py::_check_overlap` (lines 24-46, the Step 7 site), `routes/schedules.py::publish_schedule` (sole caller, line 99), `routes/schedules.py::create_schedule` (lines 49-66 — does NOT call `_check_overlap`, contradicting the PRD's "created or published"), `services/pricing.py::schedule_in_force` (lines 27-38, assumes single-PUBLISHED invariant maintained by supersession), `routes/schedules.py:124-130` (supersession cascade in publish).
  - (c) Wording adjustment: narrowed the trigger from "being created or published" to "being published" to match impl (creating overlapping DRAFTs is permitted); added the supersession carve-out scoped to "open-ended (`effective_to` is null) and `effective_from` strictly earlier than the new schedule's"; kept the rejection behavior for bounded priors and back-filling publishes.

## Step 9: Complete PRD — 2026-08-10T16:31:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1107_membership_association_dues_renewal/workspace/PRD_COMPLETED.md` is written (copied from PRD_FINALIZED.md, then edited in place; all edits are in-paragraph — no new sections).

## Summary

- **Source vs output:** PRD_FINALIZED.md = 279 lines / 44,812 chars; PRD_COMPLETED.md = 279 lines / 51,154 chars. Char delta: **+6,342** (30 diff hunks).
- **Counts:** 21 ambiguity-pins, 10 mismatch-revisions (31 total changes).

### Changes

- **§2.3** — revise — mismatch — `limit`/`offset` actually applied only by GET `/api/members` and GET `/api/dues-invoices`; all other list endpoints ignore them and return the full filtered set with meta `limit`=result count (10 when empty), `offset`=0, `has_more`=false; out-of-range values clamped, unparseable values fall back to defaults — `routes/members.py:17-31`, `routes/invoices.py:24-38` vs full-set pattern at `routes/schedules.py:85-87`, `routes/members.py:211-235`, `routes/lifecycle_ops.py:94-96`
- **§2.5** — insert — ambiguity — endpoint-local guard placement: `ERR_MEMBER_NOT_GRACE` after rules (1)–(3), retry-cap (11) before invoice-state (6) on payments; `ERR_VERIFICATION_BLOCKED` after state check; `ERR_REINSTATEMENT_HAS_PENDING` before window check; `ERR_NO_AUTO_RENEW_ACTIVE` standalone; invoice-/listing-keyed endpoints (except refund) resolve existence before auth; unknown path/method → `ERR_NOT_FOUND`; unexpected failure → `ERR_INTERNAL` 500 — `routes/invoices.py:99-135`, `routes/members.py:108-124,238-243`, `routes/lifecycle_ops.py:100-114`, `app.py:23-37`
- **§2.8** — revise — mismatch — `expected_member_version` validated only when supplied; omission is not rejected; field ignored on all other endpoints — `routes/members.py:171-174`, `routes/lifecycle_ops.py:51-54`
- **§2.9** — insert — ambiguity — logical clock frozen between set calls; never advances with wall time — `db.py:8-20`
- **§3.1** — insert — ambiguity — omitted category boolean flags default `false`, integer windows default `0` — `routes/reference.py:29-33`
- **§3.1** — revise — mismatch — chapter `code` uniqueness not enforced; no endpoint transitions chapter status (`SUSPENDED`/`DISSOLVED` never produced) — `routes/reference.py:49-60`
- **§3.1** — revise — mismatch — cycle-policy `code` uniqueness not enforced; no endpoint retires a policy — `routes/reference.py:72-85`
- **§3.2** — revise — ambiguity — "most recent prior" pinned to greatest `effective_from`; latest-`noticed_at` notice consulted; notice gap measured in whole days, partial day discarded — `routes/schedules.py:101-119`
- **§3.2** — revise — ambiguity — notice `SENT`/`CANCELLED` admitted by model but never produced — `routes/schedules.py:150-166` (no writer)
- **§3.2** — revise — mismatch — supersession of other `PUBLISHED` schedules happens immediately at publish, in the same commit (not at `effective_from`) — `routes/schedules.py:124-131`
- **§3.3** — insert — ambiguity — `joined_at` optional, defaults to current logical instant — `routes/members.py:67`
- **§3.3** — revise — ambiguity — terms never leave `OPEN`; `CLOSED`/`VOID` never produced — `services/lifecycle.py:295-304`
- **§3.4** — revise — ambiguity — anniversary `period_start` = most recent anniversary of `joined_at` on/before issuance instant; Feb 29 → Feb 28 clamp — `services/pricing.py:19-24,66-75`
- **§3.4** — revise — ambiguity — calendar anchor-day clamps to month length; `days_remaining` computed between calendar dates — `services/pricing.py:41-52,86-87`
- **§3.4** — insert — ambiguity — no `PUBLISHED` schedule in force → `ERR_NOT_FOUND`; hard precondition for registration and reinstatement filing; sweep silently skips unpriceable members — `services/pricing.py:60-62`, `services/scheduler.py:50-53`
- **§3.5** — revise — mismatch — only *accepted* submissions append a `PaymentAttempt`; attempt list ordered by `attempt_index` ascending — `routes/invoices.py:87-95,127-148`
- **§3.5** — insert — ambiguity — settling does not advance `current_period_start/end` except via the grace-recovery cascade — `services/lifecycle.py:342-373`
- **§3.5** — revise — mismatch — `FAILED_FINAL` entered only via `DECLINED_HARD`; at 5 failed attempts further submissions are rejected `ERR_RETRY_EXHAUSTED` with no state change (no cap-triggered transition) — `routes/invoices.py:127-131,157-159`
- **§3.5** — insert — ambiguity — refund window check skipped when member has no `current_period_end`; refund resets both `current_period_start` and `current_period_end` to the latest-ending still-`SETTLED` term — `routes/invoices.py:175-178,193-205`
- **§3.7** — revise — mismatch — recovery-from-grace term was already opened by the sweep with `opened_by=RENEWAL`, not opened at recovery — `services/scheduler.py:38-53`, `services/lifecycle.py:367-371`
- **§3.7** — insert — ambiguity — lapse timestamp recorded from logical clock at the `LAPSED` transition — `services/scheduler.py:100-101`
- **§3.7** — insert — ambiguity — back-dues invoice: `membership_term_id` null, pins schedule in force at most recent walked period, `due_at` = filing instant — `routes/lifecycle_ops.py:116-117`, `services/lifecycle.py:307-321`
- **§3.7** — insert — ambiguity — approve precondition error mapping: `ERR_INVALID_STATE` for member-state/back-dues failures, `ERR_REINSTATEMENT_WINDOW_EXPIRED` for window failure — `routes/lifecycle_ops.py:147-158`
- **§3.8** — insert — ambiguity — enrollment not conditioned on member status; duplicate enrollments allowed, each appends a row — `routes/lifecycle_ops.py:26-43`
- **§3.8** — insert — ambiguity — revoke with no `ACTIVE` authorization → `ERR_INVALID_STATE` — `routes/lifecycle_ops.py:55-61`
- **§3.8** — revise — mismatch — auto-renew read returns a list of all authorization rows, not 0–1 — `routes/lifecycle_ops.py:88-96`
- **§3.8** — revise — ambiguity — lookahead window = 30 days; renewal priced as of `current_period_end`; issuance dedup (only unpaid invoices with `due_at` at/after cpe suppress; settled invoices do not); silent skip when unpriceable; auto-charge gated on member `ACTIVE`/`GRACE`, never charges back-dues invoice, at most one invoice per member per sweep, simulated outcome always `SUCCEEDED` — `db.py:85`, `services/scheduler.py:25-76`
- **§3.9** — revise — ambiguity — risk-score recompute trigger points pinned (verify, payment outcomes, refund, reinstatement approve, grace/lapse transitions); other states keep last score — `services/lifecycle.py:180-208` and call sites
- **§3.9** — insert — ambiguity — no endpoint records benefit usage events, so the usage component is always 30 — `db.py:82`, `services/lifecycle.py:202-205`
- **§3.9** — insert — ambiguity — inverse propagation on recovery: `SUSPENDED` entitlements → `ACTIVE` with `suspended_at` cleared, `COVERAGE_SUSPENDED` invoices → `COVERAGE_ACTIVE` — `services/lifecycle.py:256-269`
- **§3.10** — insert — ambiguity — `occurred_at` optional, defaults to current logical instant — `routes/members.py:273`
- **§4** — revise — mismatch — auto-renew GET row description changed to "List the member's auto-renew authorizations (one row per enrollment)" — `routes/lifecycle_ops.py:88-96`
