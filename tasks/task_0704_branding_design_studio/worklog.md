# Worklog — task_0704_branding_design_studio

## Step 1: Task directory — 2026-06-29T10:10:59.000Z

Task directory `tasks/task_0704_branding_design_studio/` was pre-created (per orchestrator args, Step 1 index scan skipped to avoid parallel-run ID contention). Verified `workspace/` subdir present and empty. `prd-bench-local-run` available at /usr/local/bin/.

## Step 2: Generate Scaffold (FINISH-ONLY resume) — 2026-06-29T10:38:00.000Z

Resume of a prior partial run: `SCAFFOLD.yaml` (§1.1–§1.7) was already complete & valid (65329 bytes, mtime 10:17) and was NOT regenerated or modified. One blocking subagent generated ONLY the two missing companion design-index files at EXPERT tier, cross-referenced to the existing `SCAFFOLD.yaml`, without reading any sibling task:
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 62793 bytes (single top-level key `scaffold_difficulty_design`, §1.8 depth index / queue A). Verified valid YAML.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 122509 bytes (single top-level key `scaffold_corner_design`, §1.9 breadth index / queue B). Verified valid YAML.
Both files confirmed present and parse cleanly with the correct single designated top-level key; `SCAFFOLD.yaml` confirmed unmodified afterward (still 65329 bytes @10:17).

Subagent verbatim summary:
> result: Generated both EXPERT-tier design-index files for task_0704; SCAFFOLD.yaml untouched, no sibling tasks read.
>
> **Files written**
> - `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1241 lines; single top-level key `scaffold_difficulty_design`; **18 depth instances** (all 9 §0.5 Difficulty Rules × 2 each: `dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`).
> - `SCAFFOLD_CORNER_DESIGN.yaml` — 2582 lines; single top-level key `scaffold_corner_design`; **63 breadth instances** (54 with full `test_recipe` + 9 `excluded_because:` stubs) across all 9 claim-extraction-guide sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model).
>
> **Verification performed**
> - Exact Step-D command passes for each file: parses with `yaml.safe_load`, and `list(d.keys())` is exactly the single expected key.
> - All formula-derived assert values were executed against §1.3 formulas in Python and pinned as literals (e.g. deposit provisional 30000 vs final 45000; invoice net 30310 at-issue / 30765 at tier-1 overdue / 31219 tier-2; license round-per-line 216 vs sum-then-round 217; retainer overage 25000 at the +5 boundary, 33000 at 16h).
> - Names unique across the union of both files; every `excluded_because.difficulty_instance` cites a real difficulty-instance name; no stub carries a `test_recipe`; every active/difficulty instance carries one.
> - `scaffold_lint.py` scanned 707 calls across all 72 instances with zero violations of the design-file rules. The 14 reported violations are all rule-(f) FK_REVERSE_UNREACHABLE tagged `SCAFFOLD / §1.1↔§1.5` — a pre-existing lint heuristic limitation on the untouchable SCAFFOLD (every flagged reverse-reachability GET is already declared in SCAFFOLD.yaml), not a defect from this work.
>
> **Constraints honored**
> - SCAFFOLD.yaml never opened for write/edit; neither output file contains §1.1–§1.7 content or the other's key; no sibling `task_*/` directory listed, globbed, grepped, or read.

## Step 4: Generate PRD — 2026-06-29T10:43:00.000Z

Subagent (clean context) read the doc-generator skill + `SCAFFOLD.yaml` only and produced `workspace/PRD.md` — **308 lines, 46627 bytes**. Both design YAMLs (§1.8/§1.9) and all sibling tasks were withheld per the no-leakage constraint. File verified present, non-trivial, and size-stable. The PRD agent ran an internal Contract-2 rule-coverage audit (entities, state machines, calculations, validation priority chain, applies_to scopes, defaults, common_fields) that returned **CLEAN** — a PRD-only reader can reconstruct every scaffold rule's specification exactly; no GAPs or REINTERPRETATIONs found. (The agent's own final wrap-up text was an artifact of that internal sub-audit; the authoritative outcome is the on-disk 308-line PRD.md + the CLEAN audit verdict.)

## Step 5: Generate Unit Tests — 2026-06-29T10:58:00.000Z

Subagent verbatim summary:
> result: 90-test PRD-bench suite generated for task_0704 (36 queue-A / 54 queue-B); 18 difficulty instances ×2 + 54 corner instances ×1, 9 stubs correctly skipped, all citations verbatim, no sibling task read.
>
> Generated complete test infrastructure, translating the two design indices into a pytest suite. Sanity checks: all 17 files parse; every `test_helpers` import resolves; all 62 `api.method()` calls map to real `ApiClient` methods; coverage audit confirms exact targets; all 102 PRD citations survive a literal grep of PRD.md; no skip/xfail markers; no scaffold leakage; exactly one `Design:` tag per test.
>
> **test_helpers/** (9 files): `__init__.py`, `types.py` (13 entity TypedDicts + 14 enums; all entities carry id/created_at/updated_at/version), `api_client.py` (62 endpoint methods), `api_errors.py` (22 error IDs + HTTP-status map), `assertions.py`, `factories.py` (12 factories), `constants.py`, `test_users.py` (StudioOps/Designer/BillingOps + entity-backed Client builder `make_client_headers`), `fixtures.py` (state-progression / hierarchy / invoice / change-order / retainer-cycle composites).
> **test_suite/** (9 files): `conftest.py` + `test_01_money_and_deposits.py`, `test_02_calculations.py`, `test_03_state_machines.py`, `test_04_cascades.py`, `test_05_gates_and_priority.py`, `test_06_intervals.py`, `test_07_validations_and_errors.py`, `test_08_entities_endpoints_rbac.py`.
> **Test counts:** Total 90 — Queue A (Difficulty) 36 (all 18 difficulty instances ×2); Queue B (Corner) 54 (all 54 non-stub corner instances ×1).
> **Instances SKIPPED: 9** — all `excluded_because` stubs (queue B), correctly NOT translated (the cited difficulty instance owns each assertion). No non-stub instance dropped for the PRD-first filter — every non-stub claim had verbatim PRD coverage with a uniquely-derivable outcome.
> No sibling task was read.

## Step 6: Generate Implementation — 2026-06-29T10:58:00.000Z

Subagent verbatim summary:
> result: Complete Python+Flask implementation of the Branding & Design Studio API; boots cleanly via `start.sh`, in-memory only, no seeding; 84 self-test assertions pass.
>
> **Files** under `workspace/implementation/`: `start.sh` (foreground launcher; reads `$PORT` default 10000, binds `0.0.0.0`, `exec python3 app.py`, guarded `pip install` only when Flask missing), `requirements.txt` (`flask==3.0.3`), `app.py` (blueprint registration, error handlers, `threaded=True`), `db.py` (in-memory store, one dict per entity keyed by id; manages id/created_at/updated_at/version), `clock.py` (logical clock default `2026-03-01T00:00:00Z`), `errors.py` (`ApiError` + 22 error-id constants + HTTP statuses), `response.py` (envelope helpers), `util.py` (UUID/req_ ids, ISO-8601 3-digit fractional, `Decimal` round-half-up money), `serialize.py`, `middleware.py` (X-User-ID/X-User-Role auth, 4 roles), `helpers.py` (RBAC, existence resolution, validation, pagination limit 1–100 default 10, entity-backed Client ownership), `services/calc.py|ledger.py|cascade.py`, `routes/*.py` (13 blueprints, all entities).
> **Stack:** Python 3 + Flask; `decimal.Decimal` ROUND_HALF_UP for all money (never float). **Storage:** in-memory dicts keyed by id; empty on every boot. **Endpoints:** every route in PRD §4 / scaffold §1.5.
> **Verified by 84 passing self-test assertions:** dual-variant deposit (provisional locked 25000 → final 35000 after +40000 change order); OCC stale-version → 412; per-line license rounding (333@20% → 400); tiered late fee (162 at 17 days); retainer overage tiers (boundary at exactly +5 overage stays tier-1); cancellation cascade from CONCEPT; zero-amount-milestone waiving at completion; deposit-credit drawdown across invoices; validation ordering (auth→authz→existence→well-formedness→state).
> **Constraints honored:** read only the four permitted files (impl-gen SKILL, INSTRUCTION.md, SCAFFOLD.yaml, PRD.md); did NOT read either design YAML, test_helpers/, test_suite/, worklog.md, or any sibling task. No entity data seeded/preloaded/hardcoded at startup (grep-verified).

## Step 3: Copy INSTRUCTION.md — 2026-06-29T10:38:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0704_branding_design_studio/workspace/INSTRUCTION.md` (1424 bytes, idempotent). `SCAFFOLD.yaml` untouched.

## Step 7: Test/Fix Loop — 2026-06-29T12:04:00.000Z

Iterations run: 2 (baseline sweep + 1 fix-and-resweep). Each sweep = 2 waves of 4 rounds (8-core host self-saturates under 8 concurrent rounds), foreground-joined with `wait`.

- Baseline 2×4 sweep: 84/90 in every one of the 8 rounds — 6 deterministic failures (no host boot-timeout ERRORs), in two clusters.
- Final 2×4 sweep after fixes: 86/86 passed in all 8 rounds (4 tests deleted → total 86).

Failing tests (union across all 8 baseline rounds, all 6 failed in 8/8 rounds — deterministic, not flakiness):
1. test_04_cascades.py::test_cancel_voids_invoice_which_reverts_milestone
2. test_04_cascades.py::test_cancelled_project_status_is_cancelled
3. test_04_cascades.py::test_cancel_compensation_no_invoiced_milestone_drift
4. test_04_cascades.py::test_cancel_reverts_single_milestone_to_pending
5. test_05_gates_and_priority.py::test_occ_stale_version_beats_activation_check_on_change_order_create
6. test_05_gates_and_priority.py::test_occ_stale_version_returns_412_not_activation_error

### Tests deleted (4) — PRD-First STEP 1b unique-derivability failure

All four built a project in DELIVERY (the only stage where an ISSUED invoice can exist, per §3.6: "Issuing is permitted only while the parent project is in DELIVERY or HANDOFF") via `_delivery_project_with_issued_invoice`, then called `cancel_project` and asserted the §3.9 unwind cascade (invoice→VOID, INVOICED milestone→PENDING) and/or CANCELLED status. The implementation rejects cancel from DELIVERY with `ERR_INVALID_STATE` ("No cancel transition from current stage"), allowing cancel only from DRAFT/DISCOVERY/CONCEPT.

PRD does not uniquely determine cancel-from-DELIVERY behavior:
- §3.2 sentence 1 says "may cancel a project at any pre-terminal stage" (broad), but its following sentences and §3.9 enumerate a cancel cascade ONLY for DRAFT, DISCOVERY, and CONCEPT — DELIVERY/HANDOFF are never given a cascade.
- The §3.9 invoice-void→milestone-revert clause is attached only to DISCOVERY/CONCEPT cancellations, where an ISSUED invoice can never exist (§3.6) — so that clause is unreachable in the only stages PRD covers; a PRD-only reader cannot derive that cancel-from-DELIVERY voids invoices.
- Two-reader divergence: Reader A implements the operative enumeration (cancel only from DRAFT/DISCOVERY/CONCEPT → ERR_INVALID_STATE from DELIVERY; this is the impl). Reader B reads "any pre-terminal stage" literally but then has no PRD-defined DELIVERY cascade and must invent one. Outcomes diverge → DELETE. Fixing the impl would require adding a DELIVERY cancel cascade not traced to any verbatim PRD sentence (forbidden by the implementation-hacking cardinal rule).

Deletions (PRD-silence category — BRANCH-ASYMMETRIC / undefined-state cascade; scaffold rule that drove generation):
- test_cancel_voids_invoice_which_reverts_milestone — Design: Difficulty/transitive_cascade/cancel_discovery_cascade_invoice_void_then_milestone_revert_depth3
- test_cancelled_project_status_is_cancelled — Design: Difficulty/transitive_cascade/cancel_discovery_cascade_invoice_void_then_milestone_revert_depth3
- test_cancel_compensation_no_invoiced_milestone_drift — Design: Difficulty/compensating_invariant/cancel_compensation_reverts_milestone_and_leaves_no_invoiced_drift
- test_cancel_reverts_single_milestone_to_pending — Design: Difficulty/compensating_invariant/cancel_compensation_reverts_milestone_and_leaves_no_invoiced_drift
Also removed the now-orphaned local helper `_delivery_project_with_issued_invoice` (only used by the 4 deleted tests). The 2 PASSING handoff-cascade tests in the same file were retained.

DOC-GENERATOR FEEDBACK (Zero-Silence violation): §3.2/§3.9 promise cancellation "at any pre-terminal stage" with "no child dangling" but only define cascades for DRAFT/DISCOVERY/CONCEPT, while the only financial children to unwind (ISSUED/OVERDUE invoices, RESERVED/CLEARED licenses) can only exist in DELIVERY/HANDOFF — which the PRD leaves undefined.

### Fixes applied to test_suite/ (2) — STEP 2 test-setup-vs-PRD consistency (faithful assertion, broken precondition)

Both OCC tests assert `expected_project_version` mismatch → `ERR_STALE_PROJECT_VERSION` (HTTP 412), which is verbatim PRD-covered (§2.7) and uniquely derivable. The bug was the setup: they called `add_milestone(...)` expecting it to bump `Project.version` and make `pv0` stale. Per PRD §2.4, a resource's `version` increments only on a mutation OF THAT RESOURCE; creating a milestone in DRAFT does not mutate the project (`base_scope_cents` stays 0 until activation, §3.2), so the impl correctly leaves `Project.version` unchanged — `pv0` stays current, OCC passes, and the change order is created (response_type "object"). Fix: replace `add_milestone(...)` with a PRD-faithful DRAFT-stage project mutation that genuinely advances `Project.version` — `api.record_deposit(sid, pid, {"amount_cents": 5000}, BO)` (§3.2 deposit recording mutates `deposit_collected_cents`, which is a project mutation → §2.4 version bump). `pv0` is then genuinely stale and OCC fires correctly. No assertion weakened; no skip/xfail added.
- test_05_gates_and_priority.py::test_occ_stale_version_beats_activation_check_on_change_order_create — setup fix (add_milestone → record_deposit).
- test_05_gates_and_priority.py::test_occ_stale_version_returns_412_not_activation_error — setup fix (add_milestone → record_deposit).

### Fixes applied to test_helpers/ (0)
None.

### Fixes applied to implementation/ (0)
None. The implementation was PRD-faithful on both clusters: it correctly restricts cancel to the PRD-enumerated DRAFT/DISCOVERY/CONCEPT, and it correctly bumps `Project.version` only on actual project mutations (deposit/activate/change-order-approval), not on child-milestone creation.

Final evidence: 8 × results.{1..8}.json on disk, each 86/86 passed.

## Step 8: Finalize PRD — 2026-06-29T12:07:00.000Z

Ran (Step 7 made 4 deletions + 2 test_suite fixes → not skipped). Subagent verbatim summary:
> **Line counts:** PRD.md = 308 lines; PRD_FINALIZED.md = 308 lines. Line-count delta: 0% (the change is an in-line revision of a single line; 1 of 308 lines modified ≈ 0.3% content-line delta).
>
> **Changes (1 edit):**
> - §3.2 — revise — replaced "may cancel a project at any pre-terminal stage" with the precise stage scope: cancel is allowed only from `DRAFT`, `DISCOVERY`, or `CONCEPT`, and any other stage (`DELIVERY`, `HANDOFF`, terminal) yields `ERR_INVALID_STATE` — `implementation/routes/projects.py:233-234`.
>
> **Per-edit pre-edit search log:**
> - Edit 1 (project cancel stage scope)
>   - (a) Subject: the set of project stages from which the `cancel` transition is defined, and the error for stages where it is not.
>   - (b) Impl paths enumerated/read: `routes/projects.py` `cancel_project` (223-239, allows only DRAFT/DISCOVERY/CONCEPT else ERR_INVALID_STATE); `services/cascade.py` `cancellation_cascade` (27-78, only DRAFT/DISCOVERY/CONCEPT, consistent with §3.9); `routes/retainers.py` `cancel_retainer` (131-143, separate entity, ACTIVE/PAUSED scope, untouched); §2.12 ERR_INVALID_STATE generic transition check consistent; grep confirmed "pre-terminal" occurs only at line 142.
>   - (c) Wording adjustment: enumerated disallowed stages explicitly and named ERR_INVALID_STATE to match impl; kept the existing DRAFT/DISCOVERY/CONCEPT cascade sentences verbatim.
>
> **OCC item (test_05 fixture fix):** No PRD edit. `routes/milestones.py` `create_milestone` only calls `db.create(db.milestones, ...)` and never touches the parent project, so Project.version is not bumped on milestone create — exactly what PRD §2.4 already determines. Pure test-setup bug, not PRD silence/mismatch; §2.4/§2.7 remain verbatim.

## Step 9: Complete PRD — 2026-06-29T12:18:00.000Z

Always runs. Full impl-vs-PRD scan starting from PRD_FINALIZED.md → PRD_COMPLETED.md. Subagent verbatim summary:
> All 11 edits applied cleanly. Line count unchanged at 308 (every change is an in-paragraph insert/revise); char delta +2019 (46,918 → 48,937).
>
> **Source vs completed:** PRD_FINALIZED.md = 308 lines / 46,918 chars; PRD_COMPLETED.md = 308 lines / 48,937 chars (+2,019 chars). 10 lines touched.
>
> **Counts:** 7 ambiguity-pins, 4 mismatch-revisions.
>
> **Per change:**
> - **§2.1 (RBAC)** — insert — ambiguity — on studio-wide list endpoints a `Client` is *filtered* to its own resources rather than rejected — routes/projects.py:96-97, invoices.py:130-133, change_orders.py:110-113, retainers.py:96-97.
> - **§2.4** — revise — ambiguity — `version` begins at `1` on creation — db.py:46.
> - **§2.7 (OCC)** — revise — mismatch — impl bumps `version` on *any* project mutation (deposit, activation, every advance, completion, cancellation), not only change-order approval — db.py:51-55.
> - **§2.9** — revise — mismatch — body required-fields/types validated *before* resolving body-referenced ids (missing-field ERR_INVALID_REQUEST beats bad-reference ERR_NOT_FOUND) — routes/projects.py:45-52.
> - **§2.10** — revise — ambiguity — license overlap considers *every* license regardless of status (a VOIDED license still blocks) — routes/licenses.py:71-75.
> - **§2.10** — insert — ambiguity — malformed-interval check runs before overlap check — routes/licenses.py:65-75, care_cycles.py:56-66.
> - **§2.12** — revise — mismatch — entity-backed Client ownership evaluated *after* resource resolution (non-existent → ERR_NOT_FOUND not ERR_UNAUTHORIZED); body-referenced existence after well-formedness — routes/projects.py:76-77.
> - **§3.2 (Project)** — revise — ambiguity — `provisional_deposit_cents`/`final_deposit_cents` present-but-`null` (not absent) before activation — routes/projects.py:65-66.
> - **§3.2 (Deposit)** — insert — ambiguity — no separate deposit entity; deposit call returns updated project (HTTP 201), `amount_cents` non-negative integer — routes/projects.py:104-113.
> - **§3.6 (Invoice)** — revise — mismatch — deposit credit drawdown is by *issuance order*, not ascending milestone `sequence_index`; a VOID invoice releases its credit back into the pool — services/ledger.py:37-56.
> - **§3.9 (Cancellation Cascade)** — insert — ambiguity — an already-REJECTED moodboard is left untouched (no version bump) during the DISCOVERY unwind — services/cascade.py:39-46.
>
> No new sections/paragraphs; full implementation/ read; response shapes cross-checked via serialize.py `view()`. Verified-aligned (unchanged): round-half-up via Decimal and all pinned rounding orders, clock default 2026-03-01T00:00:00Z, ISO-8601 3 fractional digits, late-fee/overage tier boundaries, pagination bounds/sort order, and all defaults (deposit/tax/markup 0, revision_limit 3, included_hours 10, is_required_for_handoff true, hours_used 0, extra_revisions 0, concept_id null).

EXIT: PRD_COMPLETED.md present (48,937 bytes). Final 2×4 sweep evidence preserved: 8 × results.{1..8}.json on disk, each 86/86 passed.
