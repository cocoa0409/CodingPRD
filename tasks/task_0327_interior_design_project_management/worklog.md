# Worklog — task_0327_interior_design_project_management

## Step 1: Create task directory — 2026-06-13T09:08:28.000Z

Created `tasks/task_0327_interior_design_project_management/` and `tasks/task_0327_interior_design_project_management/workspace/` (pre-assigned ID; no ./tasks/ scan performed to avoid ID contention). Verified `./INSTRUCTION.md` exists for Step 3 copy.

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-13T09:35:02.000Z

All enum values declared in entity constraints are produced by transitions/initialization — no dead-end states. Every state machine's full enum set is reachable.

The scaffold is complete and fully validated. Let me produce the final summary.

## Summary

Generated all three Expert-difficulty scaffold artifacts for **Interior Design Project Management** into `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0327_interior_design_project_management/`, built fresh from the scenario + skill spec only (no sibling tasks consulted). `scaffold_lint.py` returns **VERDICT: clean lint**.

**Complexity profile:** workflow_orchestration + ledger_reconciliation; hybrid topology; cyclic/branching/compound state-machine shapes; peer_roles; immediate consistency. Layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **13 entities:** Project (aggregate root with computed budget ledger + posture), Client, Room, MoodBoard, FFEItem (catalog), DesignSelection, Vendor, ProcurementOrder, OrderLine, RevisionRequest, PunchListItem, TimeEntry, PaymentReceipt. 16 FKs, all with reverse-reachability GETs.
- **8 state machines:** Project lifecycle (BRIEFING→…→CLOSED + ON_HOLD), Project posture (compound derived gate OPEN/BUDGET_REVIEW/FROZEN), Room (with APPROVED→REWORK compensation), MoodBoard, DesignSelection, ProcurementOrder (branching pipeline + cancel/return branches), RevisionRequest (cyclic resubmit loop), PunchListItem, TimeEntry. Plus 2 OCC concurrency rules on Project.version (order-place, deposit-record).
- **6 calculations:** selection_line_net, order_subtotal (round-then-sum pinned), design_fee_final (FLAT/HOURLY/MARKUP with provisional vs final variants), budget_health (tiered threshold), deposit_waterfall (created_at-ASC allocation), expected_delivery (max lead + vendor buffer).
- **15 ordered validations**, **63 endpoints**, **28 error codes**, **4 roles** (StudioAdmin/Designer/ProcurementCoordinator opaque; Client entity_backed:Client).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** all 9 rules × 2 = **18 instances**, each with executable structured setup chains and code-computed literal asserts (e.g. hourly 52500/41250, markup 31468/19468, round-then-sum 64893 not 64894, budget util exactly 0.80→GREEN, deposit conservation 114893, half-open window adjacency).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** breadth probe across 9 guide sections — **35 active instances + 6 excluded_because stubs** (each referencing an existing §1.8 instance) covering creation/not-found/required-fields/duplicates/system-field snapshots, invalid-transition & terminal lockdown, computed fields, cross-entity validations, RBAC denials incl. entity_backed owner mismatch, 401 auth, and all OCC/derived-field/conditional-flag layers.

**Validation performed:** clean lint; all grounds references resolve into §1.1–§1.7; unique instance names across both files; precondition replay of every setup chain (no from-state/posture/advance/close violations — fixed two ordering bugs found mid-build); OCC freshness audit (no stale positive-test versions); enum closure (every declared state produced); no forbidden concurrency vocabulary; design keys confined to their own files.

## Step 3: Copy shared files — 2026-06-13T09:35:28.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0327_interior_design_project_management/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-13T09:42:07.000Z

Generated `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0327_interior_design_project_management/workspace/PRD.md` — a prose PRD for the **Interior Design PM API** (domain `interior-design-pm`, mounted at root `/`). 333 lines.

### Structure
- **§1 Introduction** — 2 paragraphs framing the studio's dual creative/operational worlds and the four cooperating roles.
- **§2 Global Specifications** — 10 subsections: RBAC (2.1), fixed verbatim Response Structure (2.2), Pagination (2.3), Identity/Timestamps/Versioning (2.4), Nested Retrieval/existence ordering (2.5), Validation Ordering (2.6), Monetary Precision/round-half-up + exact-ratio utilization (2.7), Budget Ledger & Posture (2.8), Cascading Reconciliation (2.9), and OCC (2.10).
- **§3 Business Logic** — 12 lifecycle-grouped subsections (onboarding → project standup → rooms/mood boards → selection/spec → order build/place → totals/committed/expected-delivery → revisions → budget health → design fee → deposit waterfall → fulfillment/cancel/return → punch list/close-out).
- **§4** 4-column endpoint table (63 rows). **§5** 2-column error table (28 codes).

### Coverage
- **Entities (13):** All entities and their fields covered, including `OrderLine` flagged explicitly as the lean entity carrying only `id`/`created_at` (no `updated_at`/`version`).
- **State machines:** Project status (6-state + ON_HOLD), Project posture (compound, priority-ordered FROZEN/BUDGET_REVIEW/OPEN gate), Room (incl. system-driven APPROVED→REWORK compensation hop), MoodBoard (incl. system accept/supersede cascades), DesignSelection, ProcurementOrder (branching pipeline + cancel/return compensation cascades), RevisionRequest (cyclic resubmit with `round_no`), PunchListItem, TimeEntry — all transitions with preconditions paired to error IDs and side effects enumerated.
- **Calculations (6):** `selection_line_net`, `order_subtotal` (round-then-sum pinned), `design_fee_final` (FLAT/HOURLY/MARKUP with provisional-vs-final variants and quarter-hour ceiling), `budget_health` (exact-ratio tiers with lower-band-inclusive boundaries), `deposit_waterfall`, `expected_delivery` — all in precise reconstructible prose, no pseudocode/fuzzy words.
- **OCC:** Both `concurrency_rules` (order place, deposit record) expressed with `expected_project_version` + `ERR_STALE_VERSION` (HTTP 412), framed purely in stale-version terms.

### Hard Contracts (all PASS)
- **Contract 1 (Field-Name Coverage):** 65 required field names, all present in backticks (verified mechanically after stripping code fences).
- **Contract 2 (Rule Coverage):** All 28 error IDs and all 56 state/enum values surface in §1–§3 narrative; validation priority ordering and placement-gate ordering stated explicitly; all cascades enumerated.
- **Contract 3 (§3 Path Purity):** 403 §3 backtick tokens scanned — 0 slash-prefixed, 0 bare HTTP methods, 0 method+path.

### Notable design decisions
- Placement-gate evaluation order spelled out (OCC → posture → vendor/window/empty) so the deterministic failure code is unambiguous.
- `ERR_VALIDATION` (400) attached to pagination-out-of-range / malformed body in §2.3, distinct from `ERR_INVALID_REQUEST` (422) and `ERR_FEE_MODEL_FIELDS` (422).
- Provisional-vs-final fee divergence (HOURLY counts SUBMITTED+APPROVED while open; MARKUP includes DRAFT subtotals while open) made explicit with both bases enumerated for sibling-branch symmetry.

## Step 5: Generate unit tests — 2026-06-13T10:12:52.000Z

NOTE (orchestrator): Steps 5 and 6 were launched concurrently in a single message. The first Step-5 subagent's socket connection dropped mid-sweep (API error, subagent_tokens:0) after writing a *partial* suite — 39 tests covering only 4 of 18 difficulty rules + 5 of 9 corner sections; 11/18 difficulty instances and several plainly-coverable corner tests (RBAC denials, 401-auth, OCC stale-version) were missing. SendMessage to resume the dropped agent was unavailable in this environment. The partial output was backed up, removed, and Step 5 was re-run from scratch with a fresh subagent. The re-run summary below is that complete run. (Step 6's impl-gen subagent completed normally in the concurrent launch.)

Generated complete test infrastructure for `task_0327_interior_design_project_management` from the two design indices only (no freelance SCAFFOLD walk).

### Files created

**test_helpers/ (9 modules):**
- `types.py` — 18 status/role enums + 13 entity TypedDicts (OrderLine correctly append-only: only `id`+`created_at`, no `updated_at`/`version`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (~60 methods)
- `api_errors.py` — `ApiErrorId` enum + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + `assert_project_ledger_invariants`
- `factories.py` — one payload factory per entity, input-fields-only, PRD-exact names, optional fields omitted
- `constants.py` — budget/fee thresholds
- `test_users.py` — shared role constants + `make_client_headers(client_id)` builder for the entity-backed Client role
- `fixtures.py` — composite setup helpers (approved-room base scenario, specified selections, draft/placed/delivered orders, deposits, OCC version reads)
- `__init__.py` — barrel export

**test_suite/ (conftest + 7 test files): 71 tests total** — test_01_crud_and_validation, test_02_rbac_and_auth, test_03_state_transitions, test_04_fee_and_budget_calculations, test_05_order_workflow_and_cascades, test_06_placement_gates_and_priority, test_07_concurrency_occ.

### Coverage accounting

**Queue A (Difficulty) — all 18 instances EMITTED, 2 tests each (36 tags):** dual_variant_calc (hourly, markup), combinatorial_formula (round-then-sum, budget-tier), non_linear_state_machine (revision cycle, order branch), transitive_cascade (revision→room→moodboard, order-return→waive/revert), priority_pair_validation_conflict (frozen>budget_gate, invalid_state>vendor_suspended), boundary_precision_check (0.80 GREEN boundary, empty-order), cross_entity_state_dependency (specify-room-approved, advance-all-rooms-approved), resource_temporal_overlap (strict-overlap, touching-endpoints), compensating_invariant (committed_cents restore, deposit conservation).

**Queue B (Corner) — all 35 active instances EMITTED, 1 test each (35 tags):** entities (8), state_machines (7), calculations (2), validations (7), rbac (4), cross_cutting_complexity_layers (6: incl. 3 OCC), endpoints (2).

**Excluded_because stubs (6, correctly left untested):** order_subtotal_round_then_sum_corner, budget_status_tier_boundary_corner, hourly_fee_variant_divergence_corner, deposit_waterfall_fill_order_corner, revision_cycle_corner, room_approved_to_rework_compensation_corner. All 6 `difficulty_instance` cross-references verified to resolve.

**No instances skipped** — every non-stub instance in both queues was PRD-covered and uniquely-derivable.

### Verification passed
- All 71 Design tags resolve to real instance names in the source YAMLs; exactly one tag per test (no untagged/dual-tagged)
- All quoted docstring citations confirmed verbatim in PRD.md (modulo inline-code backticks)
- No `scaffold`/`§`/`Table` leakage in generated code; no `skip`/`skipif`/`xfail`
- Entity-backed Client identity threaded via `make_client_headers` everywhere ownership matters
- All 18 files compile

## Step 6: Generate implementation — 2026-06-13T10:12:52.000Z

(Completed in the concurrent Step-5/6 launch; physical isolation held — impl-gen started before `test_suite/` existed.)

Built a complete Python + Flask in-memory REST API at `workspace/implementation/`.

### Files created (11)
- `start.sh` — foreground launcher (executable)
- `requirements.txt` — `flask==3.0.3`
- `app.py` — entry point, error handlers, all 63 routes grouped by resource
- `db.py` — in-memory dict store, UUID/timestamp/version helpers
- `errors.py` — `ApiError` + error_id→HTTP status catalogue (PRD §5)
- `response.py` — success/error envelope (`meta`/`response_type`/`data`), `req_` IDs, ISO-8601 UTC with 3 fractional digits
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, role checks
- `validation.py` — body field typing/range checks, pagination parsing
- `lookup.py` — existence (404) + Client ownership (403) helpers, sorted pagination
- `services.py` — calculation engine + project ledger recompute
- `serializers.py` — per-entity output field whitelists (strips internal `_seq`; OrderLine carries only id/created_at)

### Endpoint count
63 routes, matching the PRD §4 endpoint table exactly across all 13 entities.

### State machines & calculations
- State machines enforced inline per transition endpoint (Project lifecycle + compound posture, Room, MoodBoard, DesignSelection, ProcurementOrder branching pipeline with cancel/return compensation, cyclic RevisionRequest, PunchListItem, TimeEntry). All cascades (room approve → board accept/supersede, order place → selection ORDERED + ledger recompute, cancel/return → selection revert + waterfall re-run, revision resolve → room compensation hop) implemented as mandatory side effects.
- Calculations in `services.py` use exact arithmetic (`Fraction` + `Decimal` `ROUND_HALF_UP`, never `float` for money): `selection_line_net` (round-once-at-line), `order_subtotal` (round-then-sum of frozen snapshots), `design_fee` provisional/final per FLAT/HOURLY/MARKUP (HOURLY quarter-hour ceiling, MARKUP committed-base sets), `budget_health` (exact-ratio tiering, lower-band-inclusive), `deposit_waterfall` (created_at-ASC fill), `expected_delivery` (max lead+buffer whole days). `recompute_project()` re-derives committed/fee/remaining/status/posture/credit as one versioned mutation.
- Posture first-match-wins (FROZEN on open BLOCKING punch → RED budget; BUDGET_REVIEW on AMBER → open revision; else OPEN) and gates order placement / advance-to-INSTALLATION / close.
- Validation order follows PRD §2.6 (auth 401 → role 403 → existence 404 → ownership 403 → request 422 → state 409 → business rules); place-order guard chain OCC→posture→vendor→window→empty per §3.5. OCC (`expected_project_version`, 412) guards place + payment.

### start.sh boot
Reads `$PORT` (default 10000), guards `pip install` behind `if ! python3 -c "import flask"` (no-op on warm reboots), `exec python3 app.py` → `app.run(host="0.0.0.0", port=PORT, threaded=True)` foreground. In-memory only — fresh boot wipes state, nothing seeded (verified: project query on fresh boot returns 404). Verified end-to-end with ~80 functional assertions across two fresh boots.

## Step 7: Run tests and iterate — 2026-06-13T10:22:21.000Z

**Iterations run:** 2 (initial sweep surfaced 8 stable failures; one batch of fixes; confirming sweep clean).

Initial sweep: 63/71 in all 8 rounds. The 8 failures were identical across every round (no flakiness) — all traced to test-helper/test bugs and one non-derivable assertion, with the PRD-faithful implementation already correct.

**Tests deleted:** None. (One assertion was removed under partial-coverage handling — see below — but no test was deleted.)

**Fixes applied to `test_helpers/`:**
- `factories.py` — `create_project_payload`: stopped unconditionally defaulting `flat_fee_cents=100000`. When the caller overrides `fee_model` to HOURLY/MARKUP, the FLAT default is now dropped so omitted fee fields default to zero, matching PRD §3.2 ("Any of these fee fields defaults to zero when omitted" / per-model consistency rule). Previously the leftover `flat_fee_cents` made every HOURLY/MARKUP setup payload internally inconsistent, so the PRD-faithful impl correctly rejected it with `ERR_FEE_MODEL_FIELDS` — breaking 4 fee tests at setup (`test_hourly_provisional_fee_*`, `test_hourly_final_fee_*`, `test_markup_order_subtotals_*`, `test_markup_provisional_fee_*`).

**Fixes applied to `test_suite/`:**
- `test_01_crud_and_validation.py` — `test_create_project_returns_201_with_initial_ledger`: removed the `design_fee_cents == 0` assertion (kept `committed_cents == 0`, status, posture, version). STEP 1c partial-coverage / STEP 1b COMPUTED-FIELD collapse: PRD §3.2 "ledger fields are initialized to zero" conflicts with §3.9 (FLAT provisional fee = `flat_fee_cents`, always shown while not CLOSED) and §2.8 ("always reflect current reality"); two divergent PRD-faithful implementations exist, so `design_fee_cents == 0` at creation is not uniquely derivable.
- `test_04_fee_and_budget_calculations.py` — 4 fee-quote reads changed from `quote["design_fee_cents"]` to `quote["provisional_design_fee_cents"]` (and added the matching `final_design_fee_cents` check in `test_flat_fee_provisional_equals_final`). More faithful to PRD §3.9: the fee-quote "returns both the provisional and final design-fee figures" as distinct values; `design_fee_cents` (a single field) is not the figure the fee-quote exposes. Fixed `KeyError` on 2 tests and aligned the others.
- `test_06_placement_gates_and_priority.py` — `test_withdraw_specified_selection_on_active_order_rejected`: changed setup from `create_placed_order` (which moves the selection to `ORDERED` per §3.5) to `create_draft_order_with_lines` (selection stays `SPECIFIED` while attached to a non-cancelled DRAFT order), and updated the trailing status assertion to `SPECIFIED`. The cited PRD §3.4 rule (`ERR_SELECTION_ON_ORDER`) fires only on a *SPECIFIED* selection attached to a non-cancelled order; an `ORDERED` selection is correctly an illegal withdraw → `ERR_INVALID_STATE`. Test bug, not an impl bug.

**Fixes applied to `implementation/`:** None. The implementation was already PRD-faithful on every failing point (FLAT provisional fee derived at creation; fee-quote returning distinct provisional/final figures; withdraw rejecting `ORDERED` selections via state-machine and `SPECIFIED`-on-DRAFT-order via `ERR_SELECTION_ON_ORDER`).

**Final state:** 8/8 parallel rounds clean, 71/71 tests passing each round, 0 failures, 0 errors. Transient `results.*.json` files removed.

## Step 8: Finalize PRD — 2026-06-13T10:26:08.000Z

(Not skipped — Step 7 had non-zero `test_helpers/` + `test_suite/` fixes revealing PRD silences around fee fields.)

**Line counts:** PRD.md = 333 lines; PRD_FINALIZED.md = 333 lines; %-delta = 0% (both edits expand existing single-line paragraphs in place — 2 paragraphs revised; 2 changed-line pairs in diff).

**Changes:**
- §3.2 — revise — "ledger fields are initialized to zero" replaced with derivation-from-starting-point: `committed_cents`/`client_credit_cents` zero, `design_fee_cents` = provisional fee (FLAT → `flat_fee_cents`; HOURLY/MARKUP → 0), `budget_remaining_cents`/`budget_status`/`posture` derived (normally OPEN) — `services.py:219-240` (recompute_project) + `app.py:150` (creation calls recompute) + `services.py:103-124` (design_fee FLAT branch).
- §3.9 — insert — pinned the fee-quote response field names: two distinct fields `provisional_design_fee_cents` and `final_design_fee_cents` (no single `design_fee_cents`), plus snapshot fields `committed_cents`/`budget_cents`/`budget_remaining_cents`/`budget_status`/`client_credit_cents`, remaining/status using provisional-while-open / final-when-closed — `app.py:279-287` (fee_quote).

**Per-edit pre-edit search log:**
- Edit 1 — subject: project ledger field initialization at creation. Paths read: `app.py` create_project (128-151); `services.py` recompute_project (219-240), design_fee (103-124), committed_cents, budget_status, run_deposit_waterfall, compute_posture; all other recompute_project callers confirmed post-creation only; grepped PRD for other initial-posture claims (§2.8 line 108 consistent). Adjustment: chose "normally OPEN" + "derived per §3.8 and §2.8" rather than asserting posture always OPEN, because a large FLAT fee can push budget_status to AMBER/RED → BUDGET_REVIEW/FROZEN even at creation; scoped FLAT/HOURLY/MARKUP split to match design_fee exactly.
- Edit 2 — subject: fee-quote response shape and field names. Paths read: `app.py` fee_quote (267-288) — sole producer of provisional/final fields; confirmed `design_fee_cents` appears only on project serializer (serializers.py:11-16), never in fee-quote; confirmed snapshot remaining/status use open_fee. Adjustment: added "consistent with §3.8" qualifier on snapshot fee selection; named exactly the keys impl emits.

**Items deliberately NOT edited (pure fixture/test bugs, PRD already determines):** factories.py fee-default fix (§3.2 already pins per-model fee consistency + defaults-to-zero); test_06 withdraw fix (§3.4 + §2.6 already uniquely determine ORDERED-selection withdraw → ERR_INVALID_STATE).

## Step 9: Complete PRD — 2026-06-13T10:31:20.000Z

(Always runs — full PRD-vs-implementation/ completeness scan starting from PRD_FINALIZED.md.)

**File metrics:** PRD_FINALIZED.md = 333 lines / 53,312 chars; PRD_COMPLETED.md = 333 lines / 54,314 chars (char delta +1,002). All edits in-paragraph on 6 existing lines (12 diff line-pairs). No new sections/paragraphs.

**Counts:** ambiguity-pins (PRD silent): 5; mismatch-revisions: 1.

**Per-change:**
- §2.1 — insert — ambiguity — Client ownership constraint on *list* endpoints applied as silent filter (owned-only results) not ERR_FORBIDDEN, in addition to query-param filters; single-resource reads/actions still raise ERR_FORBIDDEN — app.py:173-174 (+ parallel list scoping 344-346, 405-407, 529-532, 669-671, 822-824, 1109-1111, 1246-1249).
- §3.4 — insert — ambiguity — `room_id` not resolving to a room of the path's project, or `ffe_item_id` resolving to no catalog item → ERR_NOT_FOUND on selection create — app.py:616-621.
- §3.5 — insert — ambiguity — `vendor_id` resolving to no vendor → ERR_NOT_FOUND on order create — app.py:782-783.
- §3.5 — insert — ambiguity — `selection_id` resolving to no selection → ERR_NOT_FOUND on order-line attach (distinct from ERR_SELECTION_ALREADY_ORDERED) — app.py:840-841.
- §3.5 — revise — mismatch — PRD said OCC version match "checked first"; impl settles state-machine legality first (non-DRAFT order → ERR_INVALID_STATE) ahead of version match. Revised to place DRAFT state-legality gate before OCC, per §2.6 — app.py:904-908.
- §3.10 — insert — ambiguity — pinned that non-outstanding orders' `balance_due_cents` equals full `order_subtotal_cents` (PRD had pinned only amount_paid_cents=0) — services.py:186-187 (+ app.py:865).

**Left unchanged:** impl is unusually faithful to an already-detailed PRD; remaining candidate behaviors already uniquely pinned by existing prose + global §2.6 ordering (state-before-business-rule errors, round-half-up line-net then round-then-sum subtotals, provisional-vs-final fee inclusion sets, posture priority, expected_delivery_at null until placement).

---

## Pipeline complete — 2026-06-13T10:31:20.000Z

All 9 steps done. Final state: 71/71 tests pass across 8/8 parallel stability rounds. Task directory contains SCAFFOLD.yaml + 2 design indices, test_helpers/ (9 modules) + test_suite/ (7 files, 71 tests), workspace/implementation/ (Python+Flask, 63 routes, in-memory), and the PRD chain PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md. Transient results.*.json removed.
