# Worklog — task_1956_sponsored_research_post_award_effort

## Step 1: Create Task Directory — 2026-08-15T02:57:00.000Z

Directory `tasks/task_1956_sponsored_research_post_award_effort/` and `workspace/` pre-created by the pipeline launcher (index 1956 assigned by launcher; orchestrator instructed to skip index computation).

## Step 2: Generate Scaffold — 2026-08-15T04:10:00.000Z

All three artifacts are complete and validated. Lint verdict (verbatim):

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1956_sponsored_research_post_award_effort/`):
- `SCAFFOLD.yaml` (§1.0–§1.7; no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Counts**
- Entities: **16** | State machines: **12** (+3 OCC concurrency rules) | Calculations: **20** | Validation priority rows: **13** | Error codes: **76** | Endpoints: **89** | Roles: **7**
- §1.8 instances: **24** (every one of the 9 difficulty rules has ≥2; rules 2/3/5/6/7/9 carry 3)
- §1.9 instances: **69** (59 active with full structured recipes + 10 `excluded_because` stubs), spanning all nine claim-extraction-guide sections; 998 recipe calls total, all lint-clean (endpoint/role/payload/capture/OCC/FK checks) plus a custom audit for placeholder closure, name uniqueness, grounds resolvability, forbidden vocabulary, and per-instance budget arithmetic.

**Harder-than-expert design decisions of note**
- **Archetype blend**: compliance/audit (SoD, retroactive-transfer dual approval) × ledger-reconciliation, on a deliberately **flat** topology (filtered-list FK reverse-reads throughout).
- **Dense interacting calculations**: NIH-style salary cap (`min(IBS/months, cap/12)` with appointment-month proration) feeds both fringe (per-line-rounding pinned vs aggregate) and effort-charged-% — whose denominator uses *uncapped* IBS, so over-cap PIs provably cannot reach nominal effort (asserted 41.67 vs committed 50.00).
- **Three pinned combinatorial modes**: min-proration branch selection (a), per-line-vs-aggregate fringe rounding diverging by exactly 1 cent (b), and F&A evaluation-order pinning where rebudgeting into EQUIPMENT requires a compensating +m/3 MTDC boost to keep the grand total equal to the obligation (c).
- **Parallel state dimensions**: GrantAward `status` × derived `posture` (OPEN/RESTRICTED/FROZEN) gating child operations; FROZEN entry cascades to auto-cancel DRAFT/SUBMITTED drawdowns.
- **Boundary instances precomputed as literals**: exactly-25%-vs-one-cent-over rebudget routing, day-60/61 interest grace (0 → 116 cents), day-90/91 retroactive transfer routing, exact-cent activation equality.
- **Three named conserved-quantity invariants**: transfer money conservation across award pairs, per-person 100.00% effort at cycle close, and LOC pool conservation (`drawn + reserved + available == eligible`) across settle/reject.
- **Determinism machinery**: logical clock with pinned startup default `2026-08-01T00:00:00Z` driving overdue sweeps/aging/posture; all ordering tie-breaks on `created_at`, never UUIDs; OCC (`expected_*_version`, always `${var}`-bound in recipes) on drawdown create, modification create, and effort certify.

## Step 3: Copy Shared Files — 2026-08-15T04:11:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1956_sponsored_research_post_award_effort/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T04:20:00.000Z

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1956_sponsored_research_post_award_effort/workspace/PRD.md`

**Section count:** 23 headings (## and ###) — 1 title + §1 Introduction + §2 with 9 subsections (2.1 RBAC, 2.2 Response Structure [verbatim], 2.3 Pagination, 2.4 Common Properties & Logical Clock, 2.5 Monetary Precision, 2.6 OCC, 2.7 Validation Ordering, 2.8 Conservation Invariants, 2.9 Derived Posture) + §3 with 9 business subsections + §4 Endpoint Definitions + §5 Error Code Catalogue.

**Word count:** 8,953 words.

**Coverage audit results:**

- **Contract 1 (Field-Name Coverage):** PASS — 136 required identifiers (entity fields, request-body keys, query params, path params, plus `budget_line_id`/`new_authorized_cents`/`current_utc`), all 136 present in backticks, 0 missing.
- **Contract 2 (Rule Coverage):** PASS — all 76 error IDs named in §2/§3 prose near their triggers; all state-machine transitions expressed as state pairs (the audit script initially flagged `SETTLED`/`REJECTED_BY_SPONSOR`, but both appear as exact uppercase strings inside the `SUBMITTED → SETTLED` / `SUBMITTED → REJECTED_BY_SPONSOR` narrative pairs, which is the required style); all 20 calculation rules rendered as precise prose (salary-cap tiering, per-line fringe rounding order, true-up, MTDC authorized-vs-accrued F&A, drawdown pool dual variants with cash/accrual filters, aging bucket boundary pins, 60-day grace + per-receivable interest rounding, waterfall, 25% rebudget significance with exactly-25-not-significant, 2,500,000-cent subaward MTDC cap with chronological min-minus-min, half-open effort windows with cap-interaction denominator, 90-day retroactive pin, 120-day FFR due / 30-day freeze grace, three conservation invariants); all three OCC rules stated with write endpoint + expected field + exact error ID + HTTP 412; 13-level validation priority order stated explicitly; every transition's side effects (four-link posting cascade, transfer apply-effects with money conservation, FROZEN drawdown auto-cancel, fan-out statement generation, fringe true-up, FFR auto-create/delete, residual deobligation) narrated.
- **Contract 3 (§3 Path Purity):** PASS — 721 backtick tokens scanned in §3, zero URL paths, zero bare HTTP methods, zero method+path combos.

**Zero-Silence Rule adjudications made:**

1. `current_utc` (clock-endpoint response field) had no natural workflow home — placed in §2.4 alongside the clock contract.
2. The 16 `ERR_*_NOT_FOUND` IDs form a homogeneous family; the scaffold's priority-4 validation lists them as one entry. Enumerated exhaustively inline in §2.7 rather than scattered, since no individual workflow narrative is their natural home.
3. `ERR_CYCLE_NOT_CERTIFYING` covers two directions (open-from-non-SCHEDULED and close-from-non-CERTIFYING); both directions stated in §3.4.
4. Drawdown terminal states `SETTLED`, `REJECTED_BY_SPONSOR`, `CANCELLED` rendered as state-pair transitions (`SUBMITTED → SETTLED`, `SUBMITTED → REJECTED_BY_SPONSOR`, auto-cancel into `CANCELLED`) in §3.6.
5. §2.2 emitted byte-verbatim from `section-2.2-response-structure.md` (including `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `"data": { }`), per the fixed-contract rule.
6. The scaffold's note "an aging report sums per-receivable rounded values, never rounds the fleet total" is preserved verbatim-in-spirit in §3.6, and the m/3 compensating-boost example for rebudget zero-sum at 5000 bps is included as a concrete illustration of the invariant.

## Step 5: Generate Unit Tests — 2026-08-15T05:05:00.000Z

**Task 1956 — Sponsored Research Post-Award & Effort Reporting** test infrastructure generated under `/home/ubuntu/github/CodingPRD/tasks/task_1956_sponsored_research_post_award_effort/`.

### Stage 1 — `test_helpers/` (9 files)
- `types.py` — 17 entity TypedDicts + 17 status/enum classes. `EffortCommitment` correctly omits `updated_at`/`version` (append-only per PRD §2.4).
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (~70 endpoints, including `get_receivables_aging` computed read and `set_clock`).
- `api_errors.py` — full 76-entry error catalog with HTTP status map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity structural assertions + LOC pool-partition invariant + money-conservation checker.
- `factories.py` — payload factories, input fields only; `create_modification_request_payload` drops `None` optional fields so REBUDGET payloads omit `extension_months`.
- `constants.py` — thresholds (90-day retroactive, 5.00pp variance, 0.75 key floor, 2,500,000-cent subaward MTDC cap, 60-day interest grace, 25% rebudget significance) + operator ids.
- `test_users.py` — shared header constants for the 5 opaque roles + `make_pi_headers`/`make_research_staff_headers` builders for the two entity-backed roles.
- `fixtures.py` — composite helpers: `create_active_award`, `post_expenditure`/`post_salary_expenditure`, `setup_transfer_pair`, `create_submitted_transfer`, `setup_prime_with_subaward`, `record_invoice`, `setup_salary_award`, cycle open/statement finders, `certify_statement` (identity-threaded), `create_drawdown` (fresh OCC version read), `setup_closeout_pending_award`.

### Stage 2 — `test_suite/` (11 files, 121 tests)
- **Queue A (Difficulty)**: 15/15 instances covered with ≥2 tests each (30 tests).
- **Queue B (Corner)**: 59/59 non-stub instances covered with ≥1 test (91 tests, several instances split across two tests).
- **Stubs**: 10 `excluded_because:` stubs NOT translated; all cross-references verified to resolve to real difficulty instances.

### Instances skipped
None. Every non-stub instance passed the PRD-first two-condition filter — the PRD verbatim-covers every asserted `error_id`, threshold, transition, and computed figure used.

### Self-audit results
- **Tag integrity**: all 121 tests carry exactly one `Design:` tag; every tag resolves to an existing instance with the correct owning rule/section; no stub tags; no untagged tests.
- **Coverage**: no difficulty instance below 2 tests; no corner non-stub instance below 1 test.
- **C1 verbatim pass**: every test's docstring contains a ≥8-word citation substring that survives a literal whitespace-normalized grep of `PRD.md` (0 failures after converting all internally-elided quotes to complete sentences).
- **Scaffold-leak sweep**: no "scaffold"/table references in generated code.
- **Skip sweep**: no `pytest.mark.skip`/`skipif`/`xfail` anywhere.
- **Compile + collection**: all modules compile; `pytest --collect-only` collects 121 tests cleanly.
- **Fixture math validation**: independently recomputed the activation grand total for all 19 distinct budget loads used by tests (all match their obligated amounts), the 90/91-day, 60/61-day, dispute, and overdue day arithmetic, and the NCE month-clamping dates (2027-06-30, 2027-09-30).

## Step 6: Generate Implementation — 2026-08-15T05:05:00.000Z

**Files created** in `/home/ubuntu/github/CodingPRD/tasks/task_1956_sponsored_research_post_award_effort/workspace/implementation/`:

| File | Role |
|---|---|
| `start.sh` | Executable foreground launcher; guarded `pip install` (no-op once Flask present), `exec python3 app.py` |
| `requirements.txt` | `flask>=3.0` |
| `app.py` | Entry point; binds `0.0.0.0:$PORT` (default 10000); ApiError/404/405/500 handlers all emit the envelope |
| `util.py` | ISO-8601 parse/format (Z-normalized), `round_half_up` via Decimal (ties away from zero), 2dp percentages, whole-day floor math, calendar-month add with day clamping |
| `errors.py` | `ApiError` + full 63-entry error catalog (IDs → HTTP status) verbatim from PRD §5 |
| `db.py` | In-memory dict stores keyed by id (16 collections), logical clock starting exactly `2026-08-01T00:00:00Z`, `stamp_new`/`touch` common-field helpers |
| `response.py` | Envelope: `meta.api_request_id` (`req_` + random), `api_request_timestamp` (3-fractional-digit UTC), `response_type` object/array/error; list meta `limit/offset/total_count/has_more` |
| `middleware.py` | `X-User-ID`/`X-User-Role` auth (401), per-endpoint role gate (403), pagination (default 10, 1–100, offset 0), deferred-shape validation tracker (shape = priority 13, checked last) |
| `services.py` | All calculation rules + cascades |
| `serializers.py` | Explicit per-entity field lists — exactly the scaffold fields, no internal-field leakage |
| `routes_core.py` / `routes_exp.py` / `routes_effort.py` / `routes_sub.py` / `routes_cash.py` / `routes_mods.py` | Route handlers grouped by resource |

**Endpoint count: 89** route handlers (AST-verified), matching the scaffold §1.5 table exactly (1 clock + 16 CRUD groups + all action endpoints + `GET /api/awards/{id}/receivables-aging`).

**Key architecture decisions:**
- **Module layout**: flat modules (not packages) for import simplicity; routes split by resource group; all business math centralized in `services.py`.
- **State machines**: encoded per-entity inline in handlers with precondition checks in PRD §2.7 priority order (auth → role → ownership → existence → OCC → state → posture → compliance → temporal → structural → referential → fiscal → shape). Where scaffold precondition order conflicted with the global priority list, PRD priority won (e.g., posture check before segregation-of-duties on transfer approve).
- **Calculations**: Decimal everywhere; pinned rounding order — monthly IBS/cap rates rounded first, then products; fringe rounded per expenditure line; late interest rounded once per receivable; subaward MTDC cap computed chronologically (period_start, created_at tie-break) with chain recompute on create/resubmit/reject; LOC pool = cash-basis, invoice = accrual-basis over uninvoiced window.
- **OCC**: `expected_award_version` (412 `ERR_STALE_AWARD_VERSION`) on drawdown/modification create, `expected_effort_statement_version` (412) on certify; award version bumps on every mutation including budget load, post, transfer approval (both awards), draw create/submit/settle/reject, receivable create/payment, modification create/apply; statement version bumps on certify/reopen *and* on silent charged-pct recompute from salary posts (PRD §2.6).
- **Logical clock**: module-level store, default pinned at 2026-08-01T00:00:00Z; `set_current_utc` triggers overdue sweep → posture recompute → FROZEN-entry drawdown auto-cancel (reservations released); receivable aging/interest computed live on read (dispute freeze stored internally as `_frozen_accrued_cents`, never serialized).
- **Posture**: stored derived field; FROZEN requires a FINAL_TECHNICAL report still `OVERDUE` with `days_overdue > 30` (days_overdue zeroed on submit per "0 while not overdue") or FFR >30 days late; cost-share shortfall at FFR submit modeled as an internal pool reduction so later recomputes preserve the floor.
- **No seeding**: stores start empty; verified empty on fresh boot.

**Verification**: three smoke suites (135 assertions) all pass against fresh `start.sh` boots — covering the four-link posting cascade, salary-cap math, F&A recompute, OCC 412s, segregation of duties, retroactive countersign path, effort fan-out/certify/reopen/close with fringe true-up, subaward invoice overlap/ceiling/MTDC-cap, receivable aging buckets + interest freeze + payment waterfall, posture RESTRICTED/FROZEN cascades, NCE/rebudget significance and zero-sum, and full FFR closeout with residual deobligation. `start.sh` boots in ~2.5s, foreground via `exec`, on `$PORT` bound to `0.0.0.0`.

## Step 7: Run Tests and Iterate — 2026-08-15T05:25:00.000Z

All 8 rounds pass 121/121.

- **Iterations run**: 2 (initial sweep → fixes → confirming sweep, 8/8 clean rounds at 121/121).
- **Tests deleted**: none.
- **Fixes applied to `test_helpers/`**: none.
- **Fixes applied to `test_suite/`**:
  - `test_04_cost_transfers.py` — added `post_salary_expenditure` to the `from test_helpers import (...)` list (was used at line 305 but never imported; the symbol IS exported via `fixtures.py`'s wildcard but the test file uses explicit imports).
  - `test_08_receivables.py` — added `GA9 = TEST_USERS["accountant_9_headers"]` module-level constant (was referenced in `TestTransferApproveGatedByTargetAwardFrozen` but never bound).
  - `test_08_receivables.py::TestReceivablePayments::test_payment_waterfall_interest_before_principal` — corrected `outstanding_total_cents` expectation from `375_116` to `375_103`. PRD §3.6 verbatim: "The accrual is the outstanding principal (`amount_cents` minus `principal_paid_cents`) multiplied by ... multiplied by billable days" — after a 50 000-cent payment that retires 49 884 of principal, accrual recomputes on the reduced 375 116 base (round(375116 × 0.10/365 × 1) = 103), giving outstanding = 425 000 + 103 − 116 − 49 884 = 375 103. The original test held `accrued_interest_cents` fixed at 116 after the pay-down, contradicting the PRD's recomputation-on-read rule ("Aging and interest recompute on every read of the receivable"). Implementation was correct; test was not.
  - `test_10_reports_and_closeout.py::TestCloseoutGates::test_close_without_accepted_ffr_returns_closeout_incomplete` and `test_ffr_submit_with_unliquidated_obligations_rejected` — removed the leading `api` positional argument from `setup_closeout_pending_award(api, "...")` calls. The fixture's first positional parameter is `award_number: str`, so `api` (an `ApiClient`) was being bound to `award_number` and JSON-serialization of the create-award payload blew up.
- **Fixes applied to `implementation/`**: none — implementation was PRD-faithful in every failure case.

## Step 8: Finalize PRD — 2026-08-15T05:35:00.000Z

**Zero edits were made** — `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md`.

### Line counts and delta

- `workspace/PRD.md`: 377 lines
- `workspace/PRD_FINALIZED.md`: 377 lines
- Delta: 0 lines, 0.0% — `diff` reports the files identical.

### Per-diff-item justification for zero edits

1. **`test_04_cost_transfers.py` missing import** — pure test bug (helper was already exported via `fixtures.py`'s wildcard; the test file just used explicit imports). Reveals no PRD silence or mismatch. No edit.

2. **`test_08_receivables.py` unbound `GA9` constant** — pure test bug (name referenced but never bound). No PRD bearing. No edit.

3. **`test_payment_waterfall_interest_before_principal` expectation 375_116 → 375_103** — the only item bearing on PRD wording, but PRD §3.6 already uniquely pins the behavior, so the correct outcome is no edit:
   - PRD line 170: "Aging and interest recompute on **every read** of the receivable and on every clock advance."
   - PRD line 170: "The accrual is the outstanding principal (**`amount_cents` minus `principal_paid_cents`**) multiplied by the sponsor's `late_payment_apr_bps` over ten thousand, divided by 365, multiplied by billable days, rounded half-up to cents once per receivable." — a closed-form function of the *current* `principal_paid_cents`, so a principal pay-down necessarily lowers the next read's accrual (round(375116 × 0.10/365 × 1) = 103).
   - PRD line 170: "The derived `outstanding_total_cents` is `amount_cents` plus `accrued_interest_cents` minus `interest_paid_cents` minus `principal_paid_cents`." → 425000 + 103 − 116 − 49884 = 375103.
   - The DISPUTED freeze clause ("stays frozen at the value computed when the dispute opened") is the explicit exception that proves accrual otherwise recomputes as a state function.
   - Implementation matches exactly: `receivable_live` (services.py:206-227) recomputes on every call, and every receivable-returning path — create (routes_cash.py:302), list (:316), get (:323), payment (:353), dispute (:374), resolve (:389), aging report (:402) — serializes through `sz.receivable` (serializers.py:203-210), which invokes `receivable_live`. The corrected test's own comment quotes PRD §3.6 verbatim as its justification, and Step 7's note states "Implementation was correct; test was not."

4. **`test_10_reports_and_closeout.py` fixture call signature** — pure test bug (`api` positionally bound to the fixture's `award_number` parameter). Reveals nothing about PRD. No edit.

Step 7 applied no `implementation/` fixes and deleted no tests, so there are no impl-side behavioral choices requiring pins either.

### Pre-edit search log

No edits were committed, so there is no per-edit wording log. For the single candidate edit subject (item 3, interest recomputation after principal pay-down), the mandatory enumeration was performed before deciding against an edit: (a) subject — receivable accrual/outstanding recomputation on read after principal payment; (b) paths enumerated and read — `implementation/services.py:206-227` (`receivable_live`), `implementation/routes_cash.py:302, 316, 323, 337-353, 368, 389, 402-403` (every receivable read/write/aging path), `implementation/serializers.py:203-210`; (c) wording adjustment — none, because all enumerated paths already conform to the existing PRD §3.6 sentences verbatim; any added wording would risk narrowing a universally-pinned rule (NO-NEW-MISMATCH), so the file was left untouched.

## Step 9: Complete PRD — 2026-08-15T05:55:00.000Z

`workspace/PRD_COMPLETED.md` written as a minimal patch over `PRD_FINALIZED.md`.

**Size**: PRD_FINALIZED.md 377 lines / 68,585 chars → PRD_COMPLETED.md 377 lines / 71,858 chars (char-delta +3,273). 24 paragraphs edited in place; no lines or sections added or removed.

**Counts**: 24 ambiguity-pins, 1 mismatch-revision (25 bullets; one edited paragraph contributes both a pin and the revision).

- §2.3 — insert — ambiguity — out-of-range/non-integer `limit`/`offset` rejected with `ERR_INVALID_REQUEST`; `has_more` = `offset` + page size < `total_count` — middleware.py:132-151, response.py:40
- §3.1 — insert — ambiguity — `authorized_cents` zero-or-more; budget-line load outside `PENDING_SETUP` → `ERR_AWARD_NOT_ACTIVE`; `mtdc_eligible_cents` zero-or-more, stored as 0 on non-SUBAWARDS lines — routes_core.py:353-372
- §3.1 — insert — ambiguity — activation from non-`PENDING_SETUP` and suspension from non-`ACTIVE` both return `ERR_AWARD_NOT_ACTIVE` — routes_core.py:225-226, 249-250
- §3.1 — revise — mismatch — dropped "(recording an optional `reason`)" from suspension; impl records no reason — routes_core.py:244-253
- §3.2 — insert — ambiguity — commitment recorded against an award not in `PENDING_SETUP`/`ACTIVE` → `ERR_AWARD_NOT_ACTIVE` — routes_core.py:416-419
- §3.2 — insert — ambiguity — non-salary `person_id` is existence-checked but not stored; non-salary `effort_pct`/`period_months` stored but unused — routes_exp.py:52, 100-104
- §3.2 — insert — ambiguity — absent `FRINGE_BENEFITS` line cannot fit a positive `fringe_cents` at posting — routes_exp.py:175-178
- §3.2 — insert — ambiguity — disallow/resubmit from wrong state → `ERR_EXPENDITURE_NOT_REVIEWABLE`; salary `amount_cents` revision ignored on resubmit — routes_exp.py:213-214, 230-231, 245-248
- §3.3 — insert — ambiguity — transfer source not `POSTED` → `ERR_EXPENDITURE_NOT_REVIEWABLE`; target line must belong to target award (`ERR_BUDGET_LINE_AWARD_MISMATCH`); `enhanced_justification` may be set at create and replaced at submit — routes_exp.py:276-291, 336-347
- §3.3 — insert — ambiguity — mirror expenditure copies `mtdc_eligible_cents`, carries zero `fringe_cents`/`over_cap_cents`, `is_cost_share` false, `submitted_by_user_id` = acting approver/countersigner — services.py:301-326
- §3.3 — insert — ambiguity — replacement `justification` on revise must again be ≥ 20 chars — routes_exp.py:444
- §3.4 — insert — ambiguity — PoP/cycle-window overlap test pinned (`project_start_date` < `period_end` and `current_end_date` ≥ `period_start`) — routes_effort.py:67-69
- §3.4 — insert — ambiguity — key-personnel floor evaluated only on `AWARD` statements; `NON_SPONSORED` keeps flag false — routes_effort.py:211-215
- §3.4 — insert — ambiguity — statement reopen requires a `reason` string, clears payroll note and key flag too, recomputes charged only for `AWARD` statements — routes_effort.py:232-244
- §3.4 — insert — ambiguity — fringe true-up adjustment skipped when the award has no `FRINGE_BENEFITS` line — services.py:358-362
- §3.5 — insert — ambiguity — subaward activate requires `DRAFT` and close requires `ACTIVE`, else `ERR_SUBAWARD_NOT_ACTIVE` — routes_sub.py:75-76, 90-91
- §3.5 — insert — ambiguity — invoice resubmit also re-checks period range (`ERR_INVOICE_PERIOD_OUT_OF_RANGE`) — routes_sub.py:328-330
- §3.5 — insert — ambiguity — `audit_reference` may come from the invoice record or the approve call (a supplied value is stored); missing prime `SUBAWARDS` line treated as authorized zero; mirror `transaction_date` = invoice `period_end`, `submitted_by_user_id` = approving officer — routes_sub.py:226-238, 249, 253, 264-265
- §3.6 — revise — ambiguity — `eligible_pool_at_submission` snapshots the award's `available_draw_pool_cents` at submission (not the eligible pool, despite the field name) — routes_cash.py:203
- §3.6 — insert — ambiguity — receivable `period_end` at or after `period_start`; billing a suspended award → `ERR_AWARD_NOT_ACTIVE` — routes_cash.py:265-266, 271-272
- §3.6 — insert — ambiguity — aging read returns `award_id` and spans every receivable of the award regardless of status — routes_cash.py:399-415
- §3.6 — insert — ambiguity — resolving a dispute clears `dispute_reason` — routes_cash.py:386
- §3.7 — insert — ambiguity — report submit and reject reset `days_overdue` to 0; accept/reject from non-`SUBMITTED` → `ERR_REPORT_NOT_SUBMITTABLE` — routes_cash.py:82, 94-95, 109-110, 119
- §3.8 — insert — ambiguity — sponsor `decision` values pinned as `APPROVE`/`DENY` — routes_mods.py:251-253
- §3.9 — insert — ambiguity — initiate-closeout requires `ACTIVE` (`ERR_AWARD_NOT_ACTIVE`); reopen and final close require `CLOSEOUT_PENDING` (`ERR_AWARD_NOT_IN_CLOSEOUT`) — routes_core.py:274-275, 298-299, 314-315

Everything else in the PRD (validation priority order, OCC endpoints, posture rules, salary/fringe/MTDC/pool/interest formulas, 100% effort conservation, cascade links, error catalogue, endpoint table with roles and filters) was verified against the implementation and already uniquely pinned — no change needed.
