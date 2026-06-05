# Worklog — task_0157_restaurant_pos_table_management

## Step 1: Create task directory — 2026-06-04T18:42:17.000Z

Created `tasks/task_0157_restaurant_pos_table_management/` and `tasks/task_0157_restaurant_pos_table_management/workspace/` (pre-allocated index per orchestration override; no auto-scan).

## Step 2: Generate scaffold (Expert band) — 2026-06-04T18:42:17.000Z

All three files written (SCAFFOLD.yaml 1648 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1316 lines, SCAFFOLD_CORNER_DESIGN.yaml 1741 lines). `scaffold_lint.py` reports VERDICT: clean lint (522 calls scanned, all §1.5-conformant, all 7 FKs reverse-reachable).

Scaffold dimensions (Expert band, §0.4):
- Entities: 15 (Restaurant, MenuItem, HappyHourWindow, DiningTable, WaitlistEntry, Seating, Check, Course, OrderItem, ItemModifier, StaffMember, StaffShift, TipPool, TipAllocation, Payment)
- State machines: 8 (DiningTable, Seating, WaitlistEntry, Course, OrderItem, Check, TipPool, Payment)
- Calculations: 5 (provisional/final subtotal, auto_gratuity, tip_pool_distribution, check_split_allocation)
- Validations: 15 (priority-ordered) · Endpoints: 58 · Errors: 15 · Roles: 4 (Manager/Server/Host/KitchenStaff) · Concurrency rules: 1 (OCC on DiningTable buss)
- §1.8 difficulty design: 18 instances (9 rules × 2) · §1.9 corner design: 41 instances (35 active + 6 excluded_because stubs across 9 sections)

Design decisions / self-audit notes:
- Archetype: pricing_engine + temporal_windowing; flat topology, cyclic state-machine shape, peer_roles, immediate consistency.
- Dual-variant hook: provisional subtotal (fire-time price snapshot) vs final subtotal (re-evaluates happy-hour windows at fired_at). Divergence forced by creating a happy-hour window after the course fires (prov 2700 vs final 1900). Second dual-variant: TipPool EVEN_BY_HOURS [6154,3846] vs WEIGHTED_BY_ROLE [7619,2381].
- Gross-subtotal comp model: subtotal includes FIRED/SERVED/COMPED at gross (only VOIDED excluded); comp_total deducts comped lines; comped_subtotal = subtotal − comp_total.
- COMP vs VOID divergence: COMP does NOT restore the 86-count; only VOID restores it. 86-count conservation invariant: available_count + Σqty(FIRED|SERVED|COMPED) == initial.
- Two overlap geometries (Rule 8): Table seating = half-open [seated_at, cleared_at) no buffer; StaffShift = closed interval expanded by min_rest_minutes.
- Depth-3 cascade originates at buss: buss frees table → promotes head WaitlistEntry → creates Seating. Void-item is second cascade (depth-2).
- All headline numeric asserts executed in Python and written as literals; tie-breaks use created_at; OCC expected_table_version always a captured ${var}.

## Step 3: Copy INSTRUCTION.md — 2026-06-04T18:42:17.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-04T18:42:17.000Z

Generated `workspace/PRD.md` — 267 lines, lossless prose projection of SCAFFOLD.yaml. Design index files NOT opened.

Major sections: §1 Introduction (dual-pricing + cascade themes, integer-cents/basis-points/server-clock conventions); §2 Global Specifications (9 subsections: RBAC, verbatim envelope, pagination, resource identity/timestamps/versioning incl. ItemModifier+TipAllocation as common_fields:false, monetary/time units, filtered-list retrieval, validation ordering priorities 1–6, occupancy cascades & atomicity, OCC on bussing); §3 Business Logic (8 lifecycle subsections); §4 endpoint table (60 rows); §5 error catalogue (15 errors).

Hard Contract reports: Contract 1 Field-Name Coverage 68/68 PASS; Contract 2 Rule Coverage 20/20 spot-checks PASS; Contract 3 §3 Path Purity 0 violations PASS.

Self-audit notes:
- Audit tooling gotcha: inline-backtick regex must strip fenced blocks first or §2.2 fence causes a false 0/68 coverage report.
- Deliberate scattering: /courses/{id}/fire semantics split §3.4 (build/fire) + §3.5 (86-guard ERR_ITEM_86 with kitchen-display fork); expected_table_version core in §2.9, workflow home §3.3. Constants embedded in context (large-party default 8, gratuity 2000 bps, comp cap 10000 bps).
- Zero-Silence: FIRED→{SERVED,VOIDED,COMPED} fork rendered with equal density; §3 has no schema tables/FK declarations; §2.2 placeholders byte-for-byte.

## Step 5: Generate unit tests — 2026-06-04T18:42:17.000Z

Generated test_helpers/ (9 files: types, api_client, api_errors, assertions, factories, constants, test_users, fixtures, __init__) and test_suite/ (8 test files + conftest). 71 test functions, all collecting cleanly.

Coverage: Queue A (Difficulty) 36 tests across all 18 instances (9 rules × 2), each ≥2 tests (primary translation + complementary distinct assertion). Queue B (Corner) 35 tests, one per each of 35 non-stub instances. Instances SKIPPED: 0 — every non-stub instance translatable, all PRD verbatim-covered and uniquely-derived. 6 excluded_because corner stubs correctly NOT translated (owned by named difficulty instance); all 6 cross-refs resolve.

Self-audit: 18/18 difficulty ≥2 tests, 35/35 corner ≥1 test, 0 bad/dual/missing tags, 0 tags pointing at stubs. PRD citations verify verbatim modulo backticks/quote/dash normalization. test_users: Server is entity_backed:StaffMember → make_server_headers(staff_id); Manager/Host/KitchenStaff opaque. No skip/xfail/skipif. Tests are integration-level, statically collected only (no impl existed at gen time).

## Step 6: Generate implementation — 2026-06-04T18:42:17.000Z

Built Python + Flask in-memory REST API at workspace/implementation/. Module layout: start.sh (guarded flask-install launcher, reads $PORT default 10000, binds 0.0.0.0, exec python3 app.py), requirements.txt (flask 3.0.3), app.py (58 routes, ~49KB), db.py (15 in-memory collections, UUID + monotonic _seq for created_at tie-breaks, epoch clock), errors.py (ApiError + 15 error-id constants), response.py (meta/response_type/data envelope, req_-prefixed id, ISO8601 UTC 3-frac-digit), middleware.py (X-User-ID/X-User-Role auth 401 + RBAC 403), common.py (validation, Decimal round-half-up & floor bps, pagination, common-field stamping), serialize.py (per-entity projection; ItemModifier+TipAllocation only id+created_at), logic.py (happy-hour eval, provisional vs final subtotal, pinned downstream resolution, tip-pool waterfall, cascades).

Endpoint count: 58. In-process verification ~50 assertions green.

PRD-ambiguity / self-audit notes:
1. Empty-course vs 86 precedence at fire: empty-course is the applicable failure when no pending items (86 guard has nothing to evaluate), then 86 guard over pending set — per §3.4 "a course with no pending items cannot fire".
2. Comp/void while PRESENTED: keep final_subtotal_cents as base while PRESENTED (not re-deriving), only re-resolve comp_total/gratuity/tax/total on locked base; provisional kept current in parallel.
3. Close-day business_date derived from restaurant current_utc (YYYY-MM-DD) per §3.7.
4. Default tip pool auto-created at close (when none exists) defaults to EVEN_BY_HOURS.
5. Sandbox note: dev server cannot bind socket under tool sandbox; verified via Flask in-process test client. No startup seeding.

## Step 7: Run tests and iterate — 2026-06-04T18:42:17.000Z

Iterations run: 2 (baseline sweep surfaced 2 deterministic failures across all 8 rounds; one fix iteration drove all 8 rounds to 71/71 green).

Tests deleted: None. Both failures were test-side bugs (faithful to PRD-covered rules, but with setup/assertion-helper mismatches), fixable without weakening any assertion.

Fixes applied to test_suite/:
1. test_03_validation_precedence_and_intervals.py — test_fire_second_course_after_present_rejected_check_not_open: reordered setup. Test verifies PRD §3.4 ("Firing a course ... legal only when ... owning check's status is OPEN"). Original setup created a second BUILDING course before present_check, making the present itself illegal per §3.7 ("Presenting ... legal only when ... no course on it is still BUILDING"); PRD-faithful impl correctly rejected the present, leaving check OPEN, so subsequent fire legitimately succeeded — failing the test. Fix: present first (legal — only course already FIRED), then create second BUILDING course on now-PRESENTED check and attempt to fire it → correctly rejected ERR_INVALID_STATE. STEP 2 test-setup fix; assertion unchanged.
2. test_06_calculations_corner.py — test_even_split_distributes_remainder_to_first_children: swapped validate_paginated(...) for validate_success(..., expected_status=201). POST /checks/{id}/split is a creation action returning HTTP 201 with a Check[] array (PRD §3.7 "split a check evenly into child checks"). validate_paginated demands HTTP 200 + list-query pagination meta a creation response does not carry. Substantive remainder-distribution assertions (dues == [1033, 1033], sum == 2066) preserved. STEP 2 assertion-helper fix; no assertion weakened.

Fixes applied to test_helpers/: None.
Fixes applied to implementation/: None — implementation was already PRD-faithful for both rules.

Final state (subagent): 8/8 parallel rounds green at 71/71. NOTE: subagent cleaned up results files; orchestrator re-runs the sweep below to verify green independently and persist the final results.{1..8}.json artifacts.

### Step 7 orchestrator verification (independent re-run)

Re-ran the 8-round parallel sweep → all 8 rounds 71/71 green; persisted as workspace/implementation/results.{1..8}.json. Then ran 32 additional confirmation rounds (scratch path, cleaned up) to surface the known per-test-server keep-alive/bind-race flakes — all 32 green. Total ≈48 green rounds on the final code (8 persisted + 32 confirmation + subagent's post-fix sweep); zero flakes surfaced. Confident green.

## Step 8: Finalize PRD — 2026-06-04T18:42:17.000Z

Created workspace/PRD_FINALIZED.md. PRD.md = 267 lines; PRD_FINALIZED.md = 267 lines; delta 0 (byte-identical). Edits made: ZERO.

Both <step_7_diff> items are pure test-side bugs against behavior the PRD already fully and uniquely determines — neither reveals a PRD silence nor a PRD/impl mismatch:
- Item 1 (fire-legality setup reorder): PRD §3.4 already states firing legal only when course BUILDING and owning check OPEN; impl (app.py:885-894) enforces exactly this. No edit.
- Item 2 (split assertion-helper swap): impl returns split as HTTP 201 array with no pagination meta; PRD §4 (creation→201), §2.2 (array response_type), §2.3 (pagination only on list endpoints) already pin every facet. Test wrongly used validate_paginated. No edit.

NO-NEW-MISMATCH pre-edit search (completeness): fire-legality cross-checked against present/reopen/close/void check ops (all consistent with §3.4/§3.7); split response shape cross-checked against response envelope + validators (split is the only 201-array endpoint). No wording change needed. Expected outcome for a step with 0 implementation fixes.

## Step 9: Complete PRD — 2026-06-05T00:00:00.000Z

(Run by orchestrator after the original claude -p process died on an API "Stream idle timeout" during Step 9; Steps 1–8 were intact, Step 7 green at 71/71 across all 8 rounds, PRD_FINALIZED.md present. Step 9 re-run via subagent.)

Source PRD_FINALIZED.md (267 lines, 41,400 chars) → PRD_COMPLETED.md (267 lines, 45,014 chars), char-delta +3,614. ambiguity-pins: 7, mismatch-revisions: 3 (10 changes total; all in-paragraph, no new sections).
- §2.1 RBAC — revise — mismatch — read authority deferred to §4 per-row role column (impl restricts some GETs to Manager) — middleware.py:22-41
- §3.3 Seating — revise — same-restaurant check precedes capacity, both raise ERR_CAPACITY_EXCEEDED — app.py:401-406
- §3.3 Buss promotion — insert — auto-promotion only considers WAITING entries of the table's own restaurant — app.py:281-284
- §3.5 Item void — insert — void re-resolves downstream money off current basis — app.py:1034, logic.py:1070-1079
- §3.5 Item comp — insert — subtotal basis for downstream re-resolution pinned — app.py:1066
- §3.5 Comp cap — insert — pre-comp subtotal = current base; prospective total tested; equal-to-cap permitted — app.py:1052-1059
- §3.7 Reopen — insert — reopen recomputes provisional + downstream totals — app.py:729
- §3.7 Close — insert — business date = YYYY-MM-DD of current_utc; pool born ACCUMULATING/EVEN_BY_HOURS/0 — app.py:750-774
- §3.7 Check void cascade — revise — PENDING lines voided but count NOT restored — app.py:790-800
- §3.7 Split — insert — no state precondition; 201 array of OPEN child Checks; parent untouched — app.py:807-835
- §3.8 Distribution — insert — zero-total-weight edge: pooled_cents to earliest shift by created_at — app.py:1306-1315
