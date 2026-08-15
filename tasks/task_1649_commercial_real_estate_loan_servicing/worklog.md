# Worklog — task_1649_commercial_real_estate_loan_servicing

## Step 1: Create task directory — 2026-08-14T04:41:00.000Z

Directory `tasks/task_1649_commercial_real_estate_loan_servicing/` and `workspace/` pre-created and pre-assigned by the pipeline launcher (Step 1 treated as DONE per invocation args).

## Step 2: Generate scaffold — 2026-08-14T05:34:40.000Z

All artifacts are complete and verified. Final report:

### Task 1649 — CRE Loan Servicing & Covenant Monitoring: scaffold generated

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1649_commercial_real_estate_loan_servicing/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1649_commercial_real_estate_loan_servicing/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — `scaffold_difficulty_design:` with 19 instances (all 9 rules ≥2; combinatorial_formula has 3 covering modes a/b/c)
- `/home/ubuntu/github/CodingPRD/tasks/task_1649_commercial_real_estate_loan_servicing/SCAFFOLD_CORNER_DESIGN.yaml` — `scaffold_corner_design:` with 58 active instances + 5 `excluded_because` stubs, across all nine taxonomy sections

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Coverage: 15 entities, 60 endpoints, 19 §1.8 instances, 58 §1.9 instances, 540 calls scanned, 0 violations.

**Complexity profile:** compliance_audit × posture_driven_gating; layers = rate_threshold_triggers, cascading_side_effects, derived_field_reconciliation, optimistic_concurrency; parallel state-machine shape (Loan carries independent payment_status × servicing_status dimensions); segregation-of-duties role model (4 roles: MasterServicer/SpecialServicer opaque, Borrower/Inspector entity-backed).

**Maximum-depth design highlights:**
- **Dual-variant calcs on different domains:** DSCR (TTM vs T3_ANNUALIZED per-loan basis — identical NOI series yields 1.1833 breach vs 1.3333 conform) and assumption fees (OUTSTANDING 8,000,000 vs ORIGINAL 5,025,000 on identical balances).
- **All three combinatorial modes:** tiered watchlist risk score with synergy branch (45+20+5+10+10=90), per-line retainage rounding pinned round-then-sum (999 vs 1000), and force-place premium evaluation order pinned single-pass on pre-advance balance (10,000,000, not the 10,204,081 fixed-point answer).
- **Cascades:** depth-3 chain statement-ACCEPT → assessment OPEN → loan WATCHLIST → reserves elevated; depth-2 inspection-POOR → entry → WATCHLIST; escalation cascade (freeze reserves, auto-reject SUBMITTED draws, auto-cancel APPROVED with hold release, suspend options); force-place → advance capitalization → LTV recompute → possible breach.
- **Boundary precision:** DSCR == threshold passes (1.2000), disbursement amount == available passes, DEFAULT at exactly 60 days delinquent, coverage == balance passes.
- **Layered error precedence:** 36-priority validation table with tested pairs state-vs-fiscal, safety-vs-temporal, and OCC(412)-before-uniqueness(409).
- **Two OCC true-race rules** (assumption-create on Loan.version, disbursement-create on ReserveAccount.version), both exercised with `${var}`-captured versions.
- **Role/ownership subtleties:** entity-backed ownership chains, 404-on-read vs 403-on-write scoping asymmetry, SoD waiver-vs-reviewer check, conditional authorization on inspection close (Inspector completes, MasterServicer cancels).

**Verification performed:** all formula-derived assert literals executed in Python (DSCR/LTV ratios at 4dp round-half-up, fees, risk score, retainage, date arithmetic for due dates/expiries/delinquency windows); name uniqueness across both design files (83 names, 0 dupes); grounds resolvability (0 unresolved); enum closure (all gaps were false positives — input-writable or transition-produced); every error code referenced by a validation; every FK has a reverse-reachability GET.

## Step 3: Copy shared files — 2026-08-14T05:34:40.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1649_commercial_real_estate_loan_servicing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T05:54:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1649_commercial_real_estate_loan_servicing/workspace/PRD.md` (364 lines). The withheld design files were never opened or referenced.

**Document design.** §1 is a two-paragraph business-context introduction (deadlines/thresholds theme, dual-dimension posture, logical clock, SoD). §2 has ten domain-derived subsections: RBAC with per-role identity translations (opaque MasterServicer/SpecialServicer; entity-backed Borrower via loan-chain `borrower_id`; entity-backed Inspector via `inspector_id`), the verbatim §2.2 block (byte-identical to the canonical source, confirmed by diff), pagination (limit 10/1/100, offset 0, `created_at` ascending with §4-flagged newest-first exceptions), the logical servicing clock (startup `2026-08-01T00:00:00Z`, never wall time), common resource properties, monetary/ratio precision (integer cents; 4dp round-half-up ratios), left-to-right nested retrieval, OCC for exactly the two guarded creates, the two-dimensional loan posture, and a 36-step validation pipeline giving explicit error precedence with worked illustrations. §3 uses seven business-process subsections (boarding → reporting/covenants → reserves/waterfall → leases/estoppels → inspections/insurance → distress/watchlist/special servicing → transfers/extensions/clock sweep), with constants embedded in narrative (15/45-day due offsets, 24-month appraisal validity, 500,000¢/5,000 sqft/60-month major-lease tests, 0.20 elevated-retainage floor, 2% force-placed premium, 365-day term, 90-day estoppel validity, 60-day approval validity, 12-month inspection freshness, 180-day maturity window, 70/85 risk thresholds, assumption-fee tiers and clamp bounds) and all formulas rendered as reconstruction-safe prose (DSCR both bases incl. the TTM no-row rule, LTV null-with-breach rule, five-component risk score with synergy and cap, per-line-round-then-sum waterfall, pinned single-pass advance capitalization, pinned seven-step sweep order). §4 is a minimal 4-column table covering all 60 endpoints; §5 is a 2-column catalogue of all 36 errors; the file ends at §5 with no audit footer.

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 106 required, 106 present, 0 missing
- endpoints[].request_body: 72 required, 72 present, 0 missing
- endpoints[].query_params: folded into scaffold input lists (limit/offset/filters); all present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 36 checked, 36 expressed in the ordered §2.10 pipeline plus per-endpoint precedence illustrations, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_loan_version/expected_reserve_account_version + ERR_STALE_VERSION/412 all named in §2.8), 0 missing
- state_machines[].transitions: 41 checked, 41 fully expressed (all from/to states, preconditions paired with error IDs, side effects incl. escalation and reinstatement cascades, cure propagation, sweep transitions), 0 missing
- calculations[]: 7 checked, 7 fully expressed (dscr_calculation, ltv_calculation, watchlist_risk_score, disbursement_waterfall, protective_advance_capitalization, assumption_fee_calculation, collection_cadence), 0 missing
- validations[] conditions: 36 checked, 36 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 60 checked, 60 expressed (including multi-endpoint scopes for ERR_OPEN_COVENANT_BREACH ×4, ERR_LOAN_NOT_CURRENT ×4, frozen-reserve ×2, estoppel gate ×2), 0 missing
- entities[].fields[] structured content: 106 checked, 106 reconstructible (defaults, null-until semantics, computed derivations, constraints), 0 missing
- sibling-branch symmetry: 12 groups checked (statement accept/reject, lease APPROVE/CONDITIONAL/REJECT, draw approve/reject, cancel SUBMITTED vs APPROVED, inspection close outcomes, assumption approve/reject/withdraw, payment transitions, estoppel/policy/option expiry paths, TTM vs T3_ANNUALIZED, OUTSTANDING vs ORIGINAL, force-placed vs ordinary cancellation, SUSPENDED→AVAILABLE/EXPIRED), 12 with equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 565
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional structural checks: all 62 enum values present verbatim; all 36 error IDs appear in §2/§3 narrative; §2.2 matches the canonical block byte-for-byte; §4 table has exactly 4 columns and 60 endpoint rows; §5 table has exactly 2 columns and 36 rows.

## Step 5: Generate unit tests — 2026-08-14T06:39:13.000Z

All checks pass. The YAML (authoritative) has 64 corner instances: 58 active + 6 stubs, and every stub's `difficulty_instance` cross-reference resolves to a real difficulty instance whose translated tests carry those assertions.

### Report

Generated complete test infrastructure for `task_1649_commercial_real_estate_loan_servicing`.

**test_helpers/** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1649_commercial_real_estate_loan_servicing/test_helpers/`):
- `types.py` — 15 entity TypedDicts + 17 status/role enums; all entities carry the full common quartet (id/created_at/updated_at/version)
- `api_client.py` — `ApiClient(GenericApiClient)` with all 60 endpoint methods, incl. `set_clock`
- `api_errors.py` — all 36 error IDs with HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` plus `assert_reserve_invariants` (available == balance - held >= 0) and null-until/attribution invariants
- `factories.py`, `constants.py` — input-only payload factories; PRD thresholds (0.20 retainage floor, 2% force-place premium, 500000¢/5000sqft/60mo major-lease tests, 70/85 risk cutoffs, fee clamp band, quarter anchors)
- `test_users.py` — opaque MasterServicer/SpecialServicer constants + mandatory `make_borrower_headers`/`make_inspector_headers` entity-backed builders
- `fixtures.py` — composite chains: `setup_watchlist_via_dscr_breach`, `setup_watchlist_via_poor_inspection`, `setup_special_servicing_loan`, `setup_funded_draw`, OCC-threading `create_draw`/`create_assumption` (fresh parent version by default, explicit token for stale tests), identity-threaded borrower/inspector calls

**test_suite/** — `conftest.py` + 9 files, **96 tests**:
- `test_01` envelope/pagination/boarding/initial-states, `test_02` auth/RBAC/ownership/SoD, `test_03` statements + DSCR/LTV covenants (incl. TTM-vs-T3 divergence pair), `test_04` reserves/waterfall, `test_05` leases/estoppels, `test_06` inspections/insurance/force-place, `test_07` assumptions, `test_08` extension options, `test_09` watchlist/posture/clock sweep

**Coverage audit (automated, passed):** 19/19 difficulty instances with ≥2 tests each (38 tests); 58/58 non-stub corner instances with ≥1 test; 6 `excluded_because:` stubs correctly untranslated (all cross-refs resolve). Every test docstring ends with exactly one verbatim `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` tag; all 149 citation fragments in docstrings survive literal grep of `workspace/PRD.md`; no skip/xfail markers; `py_compile` and `pytest --collect-only` clean (96 collected).

**PRD-first adjudication notes:** one instance assertion was deliberately not hard-coded — the `dscr_exactly_at_threshold` instance's parenthetical "17999999 -> 1.1999" is arithmetically wrong (71,999,996/60,000,000 rounds to 1.2000 at 4dp), so the below-threshold companion test uses NOI 17,999,000 → 1.1999, which genuinely breaches. Initial `version == 1` at creation is not asserted anywhere (PRD never pins the initial value); only int ≥ 1 and cascade-advance ordering are checked.

## Step 6: Generate implementation — 2026-08-14T06:39:13.000Z

Done. The implementation is complete and verified.

### What was built

A complete Python + Flask implementation of the CRE loan servicing API in `/home/ubuntu/github/CodingPRD/tasks/task_1649_commercial_real_estate_loan_servicing/workspace/implementation/`:

- **`start.sh`** — executable launcher; guards the pip install behind `python3 -c "import flask"` so per-test reboots are fast; `exec python3 app.py` in foreground, bound to `0.0.0.0:$PORT` (default 10000).
- **`app.py`** — Flask entry point, blueprint registration, error handlers (`ApiError` → envelope; unknown paths → 404 `ERR_NOT_FOUND` envelope).
- **`db.py`** — in-memory stores (all empty at boot; no seeding) plus the logical servicing clock starting at exactly `2026-08-01T00:00:00Z`.
- **`errors.py`** — all 36 error IDs with their exact HTTP statuses from the catalog.
- **`response.py`** — exact scaffold envelope: `meta` (`api_request_id` with `req_` prefix, 3-fractional-digit `api_request_timestamp`), `response_type` (`object`/`array`/`error`), `data`; pagination fields `limit`/`offset`/`total_count`/`has_more` inside `meta` for list responses.
- **`middleware.py`** — auth pipeline: `X-User-Role`/`X-User-ID` presence, entity-backed resolution for `Borrower`/`Inspector` (401), role-list authorization (403), borrower loan-chain ownership (403 `ERR_OWNERSHIP_MISMATCH`), out-of-scope reads as 404.
- **`services/`** — posture engine (PERFORMING↔WATCHLIST auto re-eval, SPECIAL_SERVICING cascade: freeze reserves, reject SUBMITTED draws, cancel APPROVED draws with hold release, suspend AVAILABLE options), DSCR (TTM 4-consecutive-quarter and T3_ANNUALIZED variants, 4dp round-half-up via `Decimal`), LTV (24-month appraisal validity, uncomputable → null + breach), auto-CURE on conforming assessments, watchlist risk score (5 components + synergy, capped at 100, entries at ≥70 with escalation_review at ≥85), the pinned 7-step clock sweep (insurance expiry → estoppel expiry → option expiry → reporting delinquency → maturity risk → maturity default → risk/servicing re-eval), and the disbursement waterfall with per-line round-then-sum retainage and the 0.20 elevated floor.
- **`routes/`** — all 60 scaffold endpoints across 13 blueprints, with validation pipeline ordering per PRD §2.10 (auth → role → ownership → existence → schema → OCC (412) → state (409) → already-reviewed → covenant breach → not-current → frozen → SoD → active entries → estoppel → retainage → resolution → duplicates/overlaps → temporal → fiscal).

### Verification

- Fresh process boots with an empty store and the clock at `2026-08-01T00:00:00Z`.
- ~120 ad-hoc smoke assertions pass covering: envelope shapes, auth/RBAC/ownership, borrower/loan boarding defaults, DSCR both variants + non-computable TTM, LTV uncomputable (null + breach + OPEN), auto-cure, waiver SoD (403), reserve deposits/holds/waterfall rounding (100001×0.10 → retained 10000), retainage release gating, elevated 0.20 floor, escalation cascade and reinstatement gates (incl. reserve target shortfall), lease suite overlap at submit, estoppel gates + 90-day expiry + sweep expiry, insurance overlap/touching-dates, coverage minimum (422), force-placement pinned evaluation order (premium 2% of pre-balance, coverage = pre-balance, reversal on cancel, replacement-coverage unblock rule), extension option window/seq/count constraints + sequencing + exercise fee + maturity month-clamping, assumption OCC (412), both fee bases with clamp behavior, execution borrower transfer, sweep idempotency (maturity-risk duplication check), and PRD §2.10 precedence examples.
- `prd-bench-local-run --test-dir test_suite --start-command "cd workspace/implementation && bash start.sh" --isolation per-test-server`: **17/17 passed** (all test files currently present: test_01 envelope/boarding, test_02 auth/RBAC/ownership). The remaining test files (03+) are still being generated externally; the implementation was hardened against the full PRD surface via the smoke suite above.

## Step 7: Run tests and iterate — 2026-08-14T06:58:00.000Z

All 8 rounds pass 96/96. Clean sweep achieved.

### Summary

- **Iterations run:** 2 (initial sweep surfaced the flake; fix applied; confirming sweep clean).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:**
  - `test_helpers/fixtures.py` — added `statement_assessments(statement_id)` helper wrapping the PRD-declared `GET /financial-statements/{id}/covenant-assessments` endpoint ("each statement also exposes the assessments it sourced", PRD §3.2/§4). Why: selection by source statement is deterministic even when multiple assessments share the same logical `assessed_at` clock instant.

- **Fixes applied to `test_suite/`:**
  - `test_suite/test_03_statements_and_covenants.py` — `test_ttm_and_t3_diverge_on_identical_noi` (failed in 7/8 rounds, `assert 1.1333 == 1.3333`): the test located the Q1'26 T3 assessment via `newest_assessment` (rows[0] of the loan-level "newest first by `assessed_at`" list). The logical clock never advances during setup (PRD §2.4), so all four T3 assessments carry an identical `assessed_at` and PRD specifies no tie-break — the implementation's random-UUID tie-break made rows[0] nondeterministic. Two PRD-faithful implementations diverge on that tie order, so the *selection path* was underdetermined (STEP 1b); the asserted values themselves are verbatim PRD §3.2 (TTM four-quarter sum vs T3 quarter×4, strict-less-than breach, `basis` copy). Per STEP 1c/2, removed the uncovered tie-order dependence and kept every covered assertion intact: `_board_divergence_pair` now also returns the Q1'26 statements, and the test selects each loan's Q1'26 assessment through its source statement (`len == 1` per PRD's "no assessment row is created at all" for uncomputable TTM quarters and one-assessment-per-acceptance for T3). Sibling test `test_t3_conforming_reassessment_auto_cures_prior_open` call site updated for the new return shape.

- **Fixes applied to `implementation/:`** none — the implementation's DSCR math, sort key (`assessed_at` desc), and statement-scoped endpoint were all PRD-faithful; the flake was purely a test-side reliance on an unspecified tie-break.

- **Audit note:** every other `newest_assessment` call site (`test_02` ×2, `test_03` ×4, `test_06` ×1, `fixtures.py` ×1) was checked — each has exactly one matching assessment in scope, so no other tie-ambiguity lurks.

## Step 8: Finalize PRD — 2026-08-14T06:58:55.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1649_commercial_real_estate_loan_servicing/workspace/PRD_FINALIZED.md` is written.

### Summary

**Line counts / delta:** PRD.md 364 lines; PRD_FINALIZED.md 364 lines; 0% line-count delta (one inline revision, no lines added or removed).

#### Changes (one bullet per change)

- **§3.2 (Quarterly Reporting and Covenant Surveillance) — revise —** the final sentence of the covenant-assessment paragraph now pins the tie-break for the loan-level assessments list: "A loan's assessments list newest first by `assessed_at` — assessments recorded at the same clock instant share an identical `assessed_at`, and such ties are broken by `id` in descending order — and filter by `assessment_type` and `status`; ..." — `implementation/routes/covenants.py:32` (`items.sort(key=lambda a: (a["assessed_at"], a["id"]), reverse=True)`; ids are random UUIDs per `implementation/db.py:6-7`).

#### Step-7 items disposition

- `test_helpers/fixtures.py` `statement_assessments()` addition — **no PRD edit**: the endpoint `GET /financial-statements/{id}/covenant-assessments` was already PRD-declared (§3.2 "each statement also exposes the assessments it sourced"; §4 table row). Pure test tooling.
- `test_03` `test_ttm_and_t3_diverge_on_identical_noi` flake — **the one PRD silence**: PRD specified "newest first by `assessed_at`" with no tie order; the impl pinned `(assessed_at desc, id desc)`. Pinned at §3.2 per above. The asserted values in the weakened test (TTM four-quarter sum, T3 ×4, strict-less-than breach, `basis` copy, one-assessment-per-acceptance) were already verbatim PRD §3.2 — no further edits.

#### Per-edit pre-edit search log

- **Edit 1 (§3.2 assessment-list ordering sentence):**
  - **(a) Subject:** ordering, including tie-breaking, of covenant assessments in list responses.
  - **(b) Impl paths enumerated and read/grepped:** `implementation/routes/covenants.py:16-34` (loan-level list; sort `(assessed_at, id)` reverse — the Step 7 site; filters `assessment_type`/`status`); `implementation/routes/statements.py:162-173` (statement-level assessments list; sort `(created_at, id)` **ascending** — opposite id tie direction); `implementation/services/posture.py:8` (order-independent `any()` OPEN-check); `implementation/services/covenants.py:108-138` (creation + `_auto_cure`, order-independent); `implementation/services/serialize.py:31-32` (per-record serializer); `implementation/db.py:6-7` (random `uuid.uuid4()` ids); plus a repo-wide grep of all `items.sort` call sites confirming no other endpoint orders assessments by `assessed_at`, and that loans/statements "newest first" lists (`routes/loans.py:90`, `routes/statements.py:112`) use `(created_at, id)` reverse — a different subject untouched by this edit.
  - **(c) Wording adjustment:** yes. Because the statement-level endpoint tie-breaks by `id` *ascending* while the loan-level endpoint tie-breaks *descending*, any global "ties break by id descending" phrasing would have created a brand-new mismatch with `routes/statements.py:171`; the clause was therefore scoped strictly inside the existing "A loan's assessments list ..." sentence, leaving the trailing "each statement also exposes the assessments it sourced" clause (governed by the §2.3 created_at-ascending default, which matches the impl) verbatim. The id tie-break is described as "descending" rather than "newest first" since UUIDs are non-temporal.

## Step 9: Complete PRD — 2026-08-14T07:16:39.000Z

The diff confirms 20 in-place line revisions covering all identified pins. Task complete.

### Summary

**Files**: Source `/home/ubuntu/github/CodingPRD/tasks/task_1649_commercial_real_estate_loan_servicing/workspace/PRD_FINALIZED.md` (364 lines, 60,078 chars) → produced `/home/ubuntu/github/CodingPRD/tasks/task_1649_commercial_real_estate_loan_servicing/workspace/PRD_COMPLETED.md` (364 lines, 62,809 chars; **+2,731 chars, 20 lines revised in place, 0 lines added/removed, no new sections**).

**Counts**: 22 ambiguity-pins, 4 mismatch-revisions (26 logical changes across 20 edited lines).

**Changes** (each `{section} — {insert|revise} — {class} — {what} — {impl ref}`):

- §2.2 — insert — ambiguity — `api_request_timestamp` is stamped from wall-clock time, the sole timestamp not reading the logical clock — `implementation/response.py:11-12`
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` — `implementation/services/pagination.py:16-29`
- §2.3 — insert — ambiguity — sort-key ties broken by `id` (ascending on oldest-first, descending on newest-first lists) — e.g. `implementation/routes/loans.py:90`, `routes/statements.py:112`
- §2.4 — insert — ambiguity — clock-set adopts any supplied instant, including one behind the current reading — `implementation/routes/clock.py:19-20`
- §2.5 — insert — ambiguity — `version` starts at 1 on creation — `implementation/services/common.py:23`
- §2.10 step 3 — revise — mismatch — path-identifier existence is established before ownership; a write naming a nonexistent path resource yields `ERR_NOT_FOUND`, not `ERR_OWNERSHIP_MISMATCH` — e.g. `implementation/routes/statements.py:29-31`
- §3.1 — insert — ambiguity — duplicate `tax_id` (borrower) and duplicate `loan_number` (loan) both draw `ERR_INVALID_REQUEST` — `implementation/routes/borrowers.py:23-25`, `implementation/routes/loans.py:41-43`
- §3.2 — insert — ambiguity — quarter alignment: `period_start` exactly 00:00:00 on quarter's first day; `period_end` any time-of-day on quarter's last day — `implementation/services/common.py:80-98`
- §3.2 — insert — ambiguity — rejection also stamps `reviewed_by_user_id` — `implementation/routes/statements.py:155-156`
- §3.2 — insert — ambiguity — uncomputable LTV (no in-date appraisal) also sets loan `current_ltv` to null — `implementation/services/covenants.py:88-98`
- §3.2 — revise — ambiguity — LTV-waiver SoD anchor is the `appraised_by_user_id` of the loan's earliest-created property carrying one; when none records an appraiser the check does not bind — `implementation/routes/covenants.py:53-63`
- §3.3 — insert — ambiguity — new reserve's `elevated_retainage`/`disbursement_frozen` initialize from the loan's current posture — `implementation/routes/reserves.py:38-39`
- §3.4 — revise — ambiguity — estoppel gate binds only `APPROVE` decisions (on `SUBMITTED` or `CONDITIONALLY_APPROVED`); `CONDITIONAL` never consults it — `implementation/routes/leases.py:150-162`
- §3.4 — insert — ambiguity — "unexpired" for the duplicate-estoppel check: `PENDING` live while `due_date` ≥ clock; `EXECUTED` live while `expires_at` strictly future — `implementation/routes/leases.py:216-226`
- §3.5 — insert — ambiguity — duplicate `license_no` → `ERR_INVALID_REQUEST` — `implementation/routes/inspections.py:29-31`
- §3.5 — revise — mismatch — inspector `active` flag recorded but never enforced by scheduling (PRD called it "the schedulable marker") — `implementation/routes/inspections.py:72-112`
- §3.5 — insert — ambiguity — role/outcome misfit at close (servicer sending `COMPLETED`, inspector sending `CANCELLED`) → `ERR_UNAUTHORIZED` — `implementation/routes/inspections.py:143-146`
- §3.5 — insert — ambiguity — at most one `ACTIVE` `INSURANCE_LAPSE` entry per loan; further lapses (sweep or cancellation) while one is `ACTIVE` open no additional entry — `implementation/services/sweep.py:59-63`, `implementation/routes/insurance.py:159-168`
- §3.5 — revise — mismatch — cancellation lapse test is "no `ACTIVE` policy of that type covering the current moment" (not merely status-ACTIVE) — `implementation/routes/insurance.py:150-157`
- §3.5 — insert — ambiguity — force-placed cancellation with zero recorded premium reverses nothing and leaves the loan untouched — `implementation/routes/insurance.py:142-145`
- §3.6 — insert — ambiguity — `source_ref` shapes: 'insurance policy {policy_id}' for lapses; null on maturity-risk and risk-score entries — `implementation/services/sweep.py:62,148`, `services/posture.py:156-158`
- §3.6 — insert — ambiguity — `escalation_review` is false on entries of every non-risk criterion — `implementation/services/posture.py:162-174`
- §3.6 — insert — ambiguity — `days_delinquent` floored at zero (reachable after a backward clock set) — `implementation/services/posture.py:83`
- §3.7 — revise — mismatch — assumption execution gates run in exactly the listed order (state → approval validity → covenant → currency), so an expired approval reports `ERR_ASSUMPTION_APPROVAL_EXPIRED` even with a concurrent `OPEN` breach, notwithstanding §2.10's global numbering (9 < 33) — `implementation/routes/assumptions.py:223-237`
- §3.7 — insert — ambiguity — execution registers the assumptor with an empty `contact_email` and without re-applying `tax_id` uniqueness — `implementation/routes/assumptions.py:239-246`

**Verification notes**: All endpoints, state transitions, calculation formulas (DSCR TTM/T3, LTV, retainage waterfall, protective-advance capitalization, assumption/extension fees, risk score), error precedence orderings, and response field shapes were walked against the PRD; everything not listed above was already uniquely pinned (including the §2.10 illustrations, sweep step order and idempotency, escalation/reinstatement cascades, and OCC token semantics).

## Step 6: Generate unit tests — 2026-08-14T00:00:00.000Z

Generated `test_helpers/` (types, api_client with 60 endpoint methods, api_errors with all 36 error IDs registered, per-entity assertions, factories, constants, role headers with entity-backed builders, composite fixtures incl. watchlist/special-servicing/funded-draw chains) and `test_suite/` (9 test files, 96 tests). Coverage: all 19 difficulty-design instances get >=2 tests each; all 58 non-stub corner-design instances get >=1 test; the 6 `excluded_because:` stubs are not translated (their owning difficulty instances cover them). Every test docstring carries verbatim PRD citations plus exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` tag. Automated audits passed: tag coverage 19/19 + 58/58, all docstring quotes verified verbatim against workspace/PRD.md, no skip/xfail markers, py_compile and pytest --collect-only clean (96 collected).
