# Worklog — task_0164_code_enforcement_violations

## Step 1: Create Task Directory — 2026-06-05T00:00:00.000Z

Created `tasks/task_0164_code_enforcement_violations/` and `tasks/task_0164_code_enforcement_violations/workspace/` via `mkdir -p`. Index 0164 pre-assigned (not auto-incremented). Difficulty target: Expert.

## Step 2: Generate Scaffold — 2026-06-05T00:00:00.000Z

All three files are written. The scaffold generation is complete.

## Summary

I generated all three scaffold artifacts for **task_0164_code_enforcement_violations** from the verbatim scenario, designed to the **Expert** band, without consulting any sibling task. The `scaffold_lint.py` verdict is **clean** (433 §1.8/§1.9 calls scanned, all conform to §1.5; all 14 FKs have reverse-reachability).

**Structural counts (Expert band):**
- **Entities: 12** — Owner, Property, FeeSchedule, Case, Complaint, Inspection, ViolationNotice, Reinspection, Fine, Hearing, AbatementOrder, Lien (Expert target 10–15 ✓)
- **Endpoints: 45** — flat top-level collections; above the 20–32 guideline because flat topology mandates a single-GET + filtered/sub-resource LIST per entity to satisfy FK reverse-reachability for 14 FKs. Per the skill, endpoint volume is explicitly not the difficulty lever; the coupling density (deep cascades, OCC, dual variants) carries the Expert difficulty.
- **Error codes: 23** (Expert target 18–30 ✓), every code referenced by a validation
- **State machines: 6** — Case (compound posture), ViolationNotice (branching + contest cycle), Hearing (continuance cycle), AbatementOrder, Lien, Complaint; 2+ non-linear on different entities (target 4+ machines ✓)
- **Calculation variants: 4 calculations**, 3 carrying 2 variants each (fine_accrual, repeat_offender_score, lien_amount) — exceeds the 3+ variant target ✓

**Design-file coverage:** SCAFFOLD_DIFFICULTY_DESIGN.yaml has all 9 §0.5 rule_ids × 2 instances = **18 instances**; SCAFFOLD_CORNER_DESIGN.yaml has **26 active corner instances + 5 `excluded_because:` stubs** across the claim-extraction taxonomy. All instance names are unique across both files (49 total); all `excluded_because.difficulty_instance` refs resolve.

**Key correctness items verified:** key separation (no design keys leaked into SCAFFOLD.yaml); all formula-derived asserts pinned to literals I computed in code (e.g., fine cap boundary 99500→100000 at day 159/160, REPEAT 25000→37500, lien principal 500000 / admin 50000 / total 550000); OCC version inputs are all `${var}` (none literal); no forbidden concurrency vocabulary; the single concurrency rule (lien-record-stale-case) is OCC-on-`Case.version` framed as strictly-sequential stale-version; all 14 FKs use the canonical `FK -> {Entity}.id` prefix; all endpoint roles are declared in the RBAC matrix. The temporal-overlap rule (§0.5 Rule 8) is satisfied with two genuinely different interval semantics on different resources — Property exclusive half-open occupancy vs Hearing minimum-gap buffer.

All three files written.

## Step 3: Copy Shared Files — 2026-06-05T00:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0164_code_enforcement_violations/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-05T00:00:00.000Z

Generated the PRD for task_0164 (Code Enforcement & Violations, EXPERT band) from the scaffold, without opening either withheld design index file.

**Output:** `workspace/PRD.md` — **280 lines**.

**Sections covered:**
- §1 Introduction (2 paragraphs — temporal/fiscal framing)
- §2 Global Specifications (9 subsections): 2.1 RBAC (all 5 roles + each `identity` translated — Registrant entity-backed, the other four opaque), 2.2 verbatim response envelope, 2.3 Pagination, 2.4 Common Properties + logical clock (FeeSchedule flagged as `common_fields: false`, carrying only `id`/`created_at`), 2.5 Compound posture + hierarchical recompute, 2.6 Money/precision/round-half-up, 2.7 OCC on lien recording, 2.8 Nested retrieval + FK resolution, 2.9 Validation ordering
- §3 Business Logic (12 lifecycle-organized subsections): config/owners/properties, case opening + single-active-case interval rule, complaints/inspections, notice issuance, repeat-offender escalation, overdue accrual (provisional vs settlement), re-inspection, contest + hearing cycle + buffer, hearing-decision fine effects, fine ledger + balance + payments, abatement, lien record/release/foreclose
- §4 Endpoint table (4 columns, 46 rows)
- §5 Error catalogue (2 columns, 23 errors)

**Hard Contract reports:** Contract 1 (field coverage 52/52, PASS), Contract 2 (rule coverage all 23 errors + OCC + 3 calculations + cascades + constants, PASS), Contract 3 (§3 path purity 373 tokens, 0 violations, PASS). Withheld design files were not read.

## Step 5: Generate Unit Tests — 2026-06-05T00:00:00.000Z

Generated complete test infrastructure for **task_0164_code_enforcement_violations** under a strict design-index-only contract.

**test_helpers/ (Stage 1) — 9 files written:** `types.py` (entity TypedDicts + status/role enums; FeeSchedule correctly omits `updated_at`/`version` per the PRD's common-fields exception), `api_client.py` (one method per PRD endpoint), `api_errors.py` (23 error IDs + HTTP-status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque-role constants + `make_registrant_headers(owner_id)` for the entity-backed Registrant), `fixtures.py` (composite chains), `__init__.py`.

**test_suite/ (Stage 2) — conftest + 8 test files, 62 test functions.**

**Coverage (all green):**
- **Difficulty queue (A): 18/18 instances, each with exactly 2 tests** (36 tests).
- **Corner queue (B): 26/26 non-stub instances covered** (≥1 test each). All 5 `excluded_because:` stubs verified to cross-reference real difficulty instances and **not** translated.

**Instances skipped: 0** — every non-stub instance passed the PRD-first two-condition filter (cap-then-multiply-then-round-once §2.6/§3.6, principal-summed-before-admin-tier lien §3.12, §2.9 validation precedence, repeat-offender freeze-vs-live split §3.5, etc.).

**Quality gates passed:** all files byte-compile; every test docstring ends in exactly one verbatim `Design:` tag resolving to a real instance; every quoted PRD citation survives literal grep of PRD.md; no skip/skipif/xfail; no scaffold/section-reference leakage; every `api.*`/`F.*` reference resolves.

## Step 6: Generate Implementation — 2026-06-05T00:00:00.000Z

Built a complete Python + Flask REST API in `workspace/implementation/`, faithful to PRD.md (wins over SCAFFOLD on conflicts) and the in-memory/no-seed contract.

**File list:** `start.sh` (foreground; reads `$PORT` default 10000, binds `0.0.0.0`, guarded dep-install), `requirements.txt` (flask==3.0.3), `app.py`, `clock.py` (logical clock §2.4), `db.py` (in-memory dict store, starts empty), `errors.py` (23-entry catalog), `response.py` (envelopes), `middleware.py` (X-User-ID/X-User-Role auth + RBAC), `routes/` (config, parties, cases, complaints, inspections, notices, reinspections, hearings, abatement, liens), `services/` (constants, calc with Decimal/ROUND_HALF_UP, domain, serialize, helpers).

**Endpoints:** 45 route handlers — every row of the PRD §4 / SCAFFOLD §1.5 table (all 5 roles, full lifecycle, sub-resource lists, `/_clock/set`).

**start.sh:** present, executable, boots fresh Flask server reading `$PORT` on `0.0.0.0` foreground, responds within ~1s. Empty-store-on-boot confirmed (no seeding at import).

**Two PRD/scaffold tensions resolved toward PRD intent:** (1) Balance floors at 0 — lien payment covers admin fee, PRD §3.12 release recomputes outstanding_balance to zero. (2) Case close gates on binding preconditions (all notices terminal + balance 0), not literal entry posture, else the release→close flow is unreachable. Re-closing a CLOSED case still yields `ERR_INVALID_STATE`.

## Step 7: Run Tests and Iterate — 2026-06-05T12:51:00.000Z

> **Reconstruction note.** The original Step 7 fix-subagent completed its loop and ran a green 8-round sweep at 15:12 local, but the orchestrator process was killed by a session/rate limit *before* its verbatim summary was written to this worklog. On resume this entry was reconstructed from durable file evidence (per-file mtimes vs. the Step 5/6 generation window, the 8 `results.*.json` files, and the diff-bearing content of the changed files) and then **re-verified by re-running the full 8-round parallel sweep under the resumed run** — `prd-bench-local-run --isolation per-test-server`, 8 concurrent rounds joined with `wait`. The verbatim per-iteration fix history is not recoverable; the net delta below is exact.

**Final sweep: 8/8 rounds green, 62/62 tests each** (re-verified 2026-06-05T20:51 local under the resumed run; results.1.json … results.8.json).

**Tests deleted: 0.** Test-function count is 62, identical to the 62 reported at Step 5 — no test was removed, so no PRD-silence deletion occurred during Step 7.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` — `raise_owner_to_repeat()`: rebuilt so each of the two prior COMPLIED notices is issued on its **own fresh Property+Case** rather than reused on one parcel. Rationale (now documented in the helper docstring): the single-active-case rule forbids a second case on a parcel with a non-CLOSED case, and a cured (COMPLIED) notice's settlement `fine_total_cents` stays in the case balance (PRD §3.10) so such a case can never reach balance 0 to be closed — therefore the rolling repeat count must key on notice status (COMPLIED/UPHELD), never on case closure. This is a fixture-precondition correction, not an assertion change.

**Fixes applied to `test_suite/`:**
- `test_02_repeat_offender.py` — aligned the repeat-offender history setup/assertions to the corrected `raise_owner_to_repeat` fixture (frozen FIRST=1.0 at issuance with 1 prior; live REPEAT at `prior_violation_count == 2`).
- `test_05_cascades_and_balance.py` — aligned the cascade/balance fixtures to the PRD-faithful accrual: the abatement-cost fine attaches to the case's most-recent UPHELD/OVERDUE notice (drive notice OVERDUE first via VACANT occupancy + advanced clock), and provisional-vs-settlement balance literals match the §3.6 accrual (e.g. 25000 provisional at 10 days overdue + 30000 abatement = 55000).

**Fixes applied to `implementation/`:**
- `routes/cases.py` — `close_case()` error precedence pinned: the close gate evaluates the **balance-zero** condition first and raises `ERR_BALANCE_OUTSTANDING` (the only error PRD names for a blocked close); the all-notices-in-benign-terminal-state precondition is retained as a defensive guard that raises `ERR_INVALID_STATE` (PRD names no error for that condition). Because any non-benign notice (ISSUED/OVERDUE/CONTESTED/UPHELD) carries a positive `fine_total_cents` that lands in `outstanding_balance_cents`, the balance check subsumes the notice-status failure on every reachable path; the notice-status branch is effectively unreachable while the balance is nonzero. Re-closing a CLOSED case still yields `ERR_INVALID_STATE`.

## Step 8: Finalize PRD — 2026-06-05T12:58:00.000Z

Step 7 made fixes (not zero), so the skip condition does not apply — Step 8 ran. Produced `workspace/PRD_FINALIZED.md` as a minimal patch of `PRD.md`.

**Line counts:** PRD.md = 280 lines, PRD_FINALIZED.md = 280 lines. Delta = 0 lines (1 line revised in place), 0.0% line-count change.

**Changes (one bullet per change):**
- §3.2 (Opening a Case / closing) — *revise* — Pinned the close-gate error precedence: the balance-zero condition is checked first (nonzero → `ERR_BALANCE_OUTSTANDING`), and only when the balance is exactly zero is the notice-status condition checked (any non-benign notice → `ERR_INVALID_STATE`). PRD previously named only `ERR_BALANCE_OUTSTANDING` and assigned no error to the notice-status condition. — `implementation/routes/cases.py:98-99, 104-106`

**Step 7 diff items NOT requiring a PRD edit (pure fixture/test corrections relying on PRD-determined behavior):**
- `test_helpers/fixtures.py` `raise_owner_to_repeat` rebuild — the behavioral facts it relies on are already pinned: repeat count keys on notice status `COMPLIED`/`UPHELD` (PRD §3.5, confirmed `calc.py:63`), a `COMPLIED` notice's fine stays in the case balance (§3.10, balance sums notices not in `DISMISSED`/`SETTLED`), and the single-active-case rule (§3.2). Pure fixture-precondition bug.
- `test_02_repeat_offender.py` / `test_05_cascades_and_balance.py` alignment — relies on PRD-determined accrual (§3.6 provisional/settlement) and abatement-cost-fine attachment to the most-recent `UPHELD`/`OVERDUE` notice (§3.11). Pure test alignment to the corrected fixture.

**Per-edit pre-edit search log:**
- Edit 1 — close-gate error precedence (§3.2): (a) Subject: the error(s) raised when a case close is blocked, and the order the balance-zero and notice-status conditions are evaluated in `close_case`. (b) Impl paths enumerated: grepped `routes/`+`services/` for `close_case`, `/close`, `closed_at`, `CLOSED`, `ERR_BALANCE_OUTSTANDING`, `ERR_INVALID_STATE`. Only case-close path is `routes/cases.py:78-110`; confirmed `routes/notices.py:72` (ISSUED notice carries positive `fine_total_cents`) and `services/domain.py:128-156` (`compute_balance` counts every notice not in `DISMISSED`/`SETTLED`), so a non-benign notice normally implies nonzero balance; notice-status branch reachable only in the narrow fully-paid-`CONTESTED` balance-0 case. Other `ERR_BALANCE_OUTSTANDING` (`liens.py:130`) is lien release (distinct, §3.12) — not touched. (c) Wording adjustment: deliberately left the pre-existing "Closing is only defined from the `LIENED` and `ACTIVE` postures" clause untouched — impl does not enforce that posture restriction (closes a zero-balance INTAKE case, per `test_07` back-to-back-case test); that is a separate, out-of-scope mismatch flagged for Step 9, not entrenched or contradicted here.

## Step 9: Complete PRD — 2026-06-05T13:04:00.000Z

Ran the full PRD-vs-`implementation/` completeness scan, starting from `PRD_FINALIZED.md`. Produced `workspace/PRD_COMPLETED.md` (the final artifact).

**Line counts / char-delta:** PRD_FINALIZED.md = 280 lines / 42366 chars; PRD_COMPLETED.md = 280 lines / 44897 chars. Char delta +2531; all edits in-paragraph (no new sections/paragraphs; 29 headers intact). 10 lines revised in place.

**Counts:** ambiguity-pins: 9, mismatch-revisions: 2.

**Per-change:**
- §2.1 — insert — ambiguity — authentication is driven solely by `X-User-Role`; a missing `X-User-ID` is not itself `ERR_UNAUTHENTICATED` (surfaces only at later ownership checks) — `middleware.py:17-24`.
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` clamped to nearest bound; non-integer values → `ERR_INVALID_REQUEST` — `services/helpers.py:67-97`.
- §2.4 — revise — ambiguity — `version` begins at `1` on creation — `db.py:55-66`.
- §3.2 — revise — mismatch — removed false "Closing is only defined from `LIENED` and `ACTIVE` postures"; close allowed from any non-`CLOSED` posture (incl. zero-balance `INTAKE`), no posture floor — `routes/cases.py:80-110`.
- §3.2 — insert — ambiguity — already-`CLOSED` case rejected with `ERR_INVALID_STATE` before the balance/notice conditions — `routes/cases.py:85-86`.
- §3.3 (complaints) — revise — ambiguity — `ERR_INVALID_STATE` for a dismiss blocked by substantiated grounds, and for triage/dismiss from a non-`RECEIVED` status — `routes/complaints.py:61-80`.
- §3.3 (inspections) — insert — ambiguity — `REINSPECTION` omitting `notice_id` → `ERR_REINSPECTION_TARGET_INVALID`; unresolvable `notice_id` → `ERR_REFERENCE_NOT_FOUND` — `routes/inspections.py:36-47`.
- §3.10 (balance) — insert — ambiguity — `outstanding_balance_cents` floored at zero; recorded abatement cost = sum of OPEN `ABATEMENT_COST` `assessed_cents` — `services/domain.py:128-156`.
- §3.10 (payment) — revise — ambiguity + mismatch — oldest-first allocation stops at first not-fully-covered fine (partial leaves OPEN); notice settlement judged by OPEN `CITATION` fines alone; payment endpoint responds `201` despite §4's general modify→200 rule — `routes/cases.py:141-170`.
- §3.11 (abatement complete) — insert — ambiguity — "most recent" = latest creation order; completion with no `UPHELD`/`OVERDUE` notice still → `COMPLETED` but creates no abatement-cost fine — `routes/abatement.py:117-157`.
- §3.12 (lien release) — insert — ambiguity — release additionally moves every `OVERDUE`/`UPHELD` notice on the case to `SETTLED` (mechanism by which balance reaches zero) — `routes/liens.py:139-143` (orchestrator-verified against source).

**Pipeline complete.** STOP condition met: `workspace/PRD_COMPLETED.md` exists. Final 8-round sweep all-green (8/8 × 62/62).

