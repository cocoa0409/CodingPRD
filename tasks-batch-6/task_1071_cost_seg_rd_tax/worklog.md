# Worklog — task_1071_cost_seg_rd_tax

Scenario: 1071. Cost-Segregation & R&D Tax-Credit Service: study scope & asset/property, engineering allocation & depreciation, tax-benefit calc & documentation, audit-support & report, fee (fixed/%), CPA coordination, look-back/amended, deliverable

## Step 1: Create task directory — 2026-07-21T14:27:08.000Z

Created ./tasks/task_1071_cost_seg_rd_tax/ with workspace/ subdirectory. Next index determined by scanning ./tasks/ (highest was task_1070_anchor).

## Step 2: Generate scaffold — 2026-07-21T14:50:00.000Z

Generated a lint-clean 3-file scaffold for **task_1071_cost_seg_rd_tax** (Cost-Segregation & R&D Tax-Credit Service).

**Profile:** Expert tier. Primary archetype ledger_reconciliation + secondary workflow_orchestration; flat topology; cyclic state-machine shape; segregation_of_duties role model; layers = dual_variant_calculation, cascading_side_effects, optimistic_concurrency, rate_threshold_triggers.

**Structural counts:**
- **10 entities:** Client, Property, Engineer, Study (central OCC parent), AssetComponent, QreLineItem, Report, AuditSupportCase, AmendedReturn, FeeInvoice
- **36 endpoints** (incl. `/_clock/set_current_utc`, default `2026-05-01T00:00:00Z`)
- **8 state machines** — non-linear cycles on Study (IN_REVIEW↔ENGINEERING) and Report (DRAFT↔REVISION_REQUESTED); linear/branching on the rest
- **5 calculations:** cost_seg_first_year_depreciation (WITH_BONUS vs WITHOUT_BONUS), rd_credit (ASC vs REGULAR), qre_qualified_amount (65% contract cap), study_fee (fixed/%), section_481a_adjustment
- **18 error codes**, **4 roles** (StudyManager opaque, Engineer & Reviewer both entity_backed:Engineer for SoD, CPA opaque), **1 concurrency rule** (amended-return create OCC on Study.version)

**Difficulty coverage:** all 9 rules × 2 = 18 instances in §1.8; 25 corner instances across 8 sections in §1.9. All formula-derived asserts pinned to code-computed literals (WITH_BONUS first-year 20994800 vs WITHOUT 4794800; ASC credit 833000 vs REGULAR 795000; §481(a) 18430800; per-component-rounding edge yields 2).

**Lint:** clean (366 calls). Fixes: api_prefix `/`, path params normalized to `{id}`; quoted grounds tokens in corner flow lists. All 3 files pass yaml.safe_load (1040 / 568 / 488 lines).

## Step 3: Copy shared files — 2026-07-21T14:50:58.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-07-21T14:57:37.000Z

Generated workspace/PRD.md (244 lines) for the Cost-Segregation & R&D Tax-Credit Service.

**Structure**: §1 Introduction; §2 Global Specifications (10 subsections: RBAC + validation priority, Response Structure, Pagination, Common Resource Properties [Engineer id/created_at only], Monetary/rate rounding + per-component-then-sum rule, Logical Clock, Hierarchical Consistency + cascades, SoD, OCC, Conserved Ledger Quantities); §3 Business Logic (7 subsections); §4 endpoint table; §5 error table.

**Counts**: 36 endpoints documented, 18 error codes. Hard Contracts (field-name coverage, rule coverage, §3 path purity) all PASS.

**Scaffold notes/ambiguities**:
- ERR_MISSING_FEE_TERMS and ERR_NO_QUALIFIED_QRE exist in error catalog but not in priority-ordered validations list; documented in prose at natural workflow homes.
- Scope-endpoint ordering: global priority places property/base-period overlap (8/9) before percent-fee cap (11).
- Two entities carry field section_481a_cents (Study and AmendedReturn) — single backtick coverage suffices.
- Withheld design files not opened.

## Step 5: Generate unit tests — 2026-07-21T15:13:00.000Z

Generated test_helpers/ (9 files) + test_suite/ (10 files, **57 tests**).
- Queue A (Difficulty): 36 tests — all 18 instances × 2 (each pair a genuinely distinct observation).
- Queue B (Corner): 21 tests — 21 of 22 non-stub instances, 1 each.
- **Skipped (1):** Corner/entities/property_missing_required_field_rejected — asserts ERR_VALIDATION for omitted required field, but PRD names ERR_VALIDATION only in §5 status table with no prose trigger. Fails coverage + unique-derivability. Gap left as gap.
- 3 excluded_because stubs correctly not translated.
- Verification: all files byte-compile; 57 tests collect; every docstring ends with exactly one Design: tag + PRD citation surviving literal grep; asserted literals independently recomputed (with-bonus 20994800 / without-bonus 4794800 / benefit 4408908; ASC 833000 / REGULAR 795000; §481(a) 18430800; fee 1102227).

NOTE: Step 5 ran synchronously (not concurrent with Step 6). Step 6 prompt explicitly forbids reading test_suite/ and test_helpers/ to preserve the isolation guarantee.

## Step 6: Generate implementation — 2026-07-21T15:22:00.000Z

Built Python + Flask in-memory implementation at workspace/implementation/ (10 files: start.sh, requirements.txt, app.py, core.py, calc.py, serializers.py, routes_core.py, routes_study.py, routes_children.py, routes_post.py).

**Endpoints: 40** (all PRD §4 + _clock).

**Key mechanics**: dual-variant cost-seg depreciation (per-component round-half-up THEN sum); dual-variant R&D credit (REGULAR base-floor + ASC 14%/6% startup; contract-research 0.65 cap at qualify); cyclic state machines (Study IN_REVIEW↔ENGINEERING, Report DRAFT↔REVISION_REQUESTED); finalize 3-link cascade (Report→FeeInvoice→client.outstanding_fee_cents); §481(a) + amend cascade; OCC expected_study_version → 412 ERR_STALE_STUDY_VERSION; conserved ledgers (total_allocated_cost_cents, outstanding_fee_cents); SoD (reviewer ≠ assigned_engineer on reject/finalize); validation priority order per §2.1. In-memory only, no seeding. Confirmed via prompt it did NOT read test_suite/ or test_helpers/.

**Judgment call flagged for Step 9**: scope with property_id that exists but not owned by study's client → ERR_NOT_FOUND (404); scaffold names no dedicated ownership error.

## Step 7: Test and iterate — 2026-07-21T15:30:00.000Z

**CLEAN FIRST-SWEEP PASS.** Iterations run: 1 (single 8-round stability sweep, run as 2 waves of 4 via workspace/sweep.sh per host operational guidance to dodge single-task self-saturation). All 8 rounds passed **57/57** (failed=0, errors=0, skipped=0 in every round). No flakiness across union of rounds.
- Tests deleted: None.
- Fixes to test_helpers/: None.
- Fixes to implementation/: None.

Since Step 7 had 0 deletions / 0 test_suite fixes / 0 test_helpers fixes / 0 implementation fixes → **Step 8 SKIPPED** (PRD.md already determined every behavior). Step 9 still runs.

## Step 8: Finalize PRD — SKIPPED

Skip condition met: Step 7 exited on first 8-round sweep with 0 iterations beyond baseline (0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, 0 implementation/ fixes). No PRD_FINALIZED.md produced. Step 9 reads from PRD.md.

## Step 9: Complete PRD — 2026-07-21T15:29:04.000Z

Produced workspace/PRD_COMPLETED.md via full PRD-vs-implementation/ scan (source PRD.md).
- PRD.md 244 → PRD_COMPLETED.md 244 lines; 34,338 → 35,284 chars (+946).
- **ambiguity-pins: 4; mismatch-revisions: 0.** Calculations, state machines, ledger conservation, SoD, OCC, validation-priority ordering, cascades all already matched PRD uniquely.

Changes:
- §3.2 — insert — ambiguity — property_id owned by a different client → ERR_NOT_FOUND (existence stage, before state check) — routes_study.py:100-102. (Resolves the impl-gen flagged judgment call.)
- §3.2 — insert — ambiguity — fixed_base_pct and avg_annual_gross_receipts_cents optional, treated as 0 when omitted — routes_study.py:152-153, calc.py:87-88.
- §2.3 — insert — ambiguity — out-of-range/non-integer limit/offset clamped/defaulted (limit<1→1, >100→100, non-int→10; offset neg/non-int→0) — core.py:212-227.
- §3.3 — insert — ambiguity — excluding a component not gated on parent study state (unlike allocation); only guard is already-EXCLUDED → ERR_INVALID_STATE — routes_post.py:72-86.
- review_note on reject accepted-but-not-persisted; PRD "may carry a free-text review_note" already permits (no promised storage), no pin needed.

## Pipeline complete — 2026-07-21T15:29:04.000Z

Final deliverable: task_1071_cost_seg_rd_tax passes **57/57 tests × 8 stability rounds** (results.{1..8}.json regenerated, all clean). Clean-first-sweep task (0 Step-7 fixes). Artifacts: SCAFFOLD.yaml (+DIFFICULTY/CORNER design), workspace/PRD.md, workspace/PRD_COMPLETED.md, test_helpers/ (9 files), test_suite/ (10 files, 57 tests), workspace/implementation/ (10 files, 40 endpoints).
