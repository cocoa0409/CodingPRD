# Worklog — task_0193_food_bank_pantry_distribution

## Step 1: Create Task Directory — 2026-06-06T10:46:41.000Z

Pre-allocated directory `tasks/task_0193_food_bank_pantry_distribution/` confirmed (with `workspace/` subfolder). Did NOT scan ./tasks for a new index (parallel-run collision avoidance). Project root: `/Users/uni/Desktop/吉/project/custom_prd_bench`. INSTRUCTION.md present at root. Scenario: Food Bank & Pantry Distribution. Difficulty: Expert (§0.4 Expert band) — to be passed to scaffold-generator only.

## Step 2: Generate Scaffold — 2026-06-06T11:01:10.000Z

All three artifacts generated; `scaffold_lint.py` reports VERDICT: clean lint (316 calls scanned, all FK reverse-reachability satisfied). SCAFFOLD.yaml=1380 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml=956 lines, SCAFFOLD_CORNER_DESIGN.yaml=1141 lines.

**SCAFFOLD.yaml counts**
- Entities: 9 — ColdStorageUnit, InventoryLot, Agency, AllocationCycle, AgencyOrder, OrderLine, ClientHousehold, DistributionEvent, PoundageReport (PoundageReport is common_fields: false)
- State machines: 5 — InventoryLot (parallel disposition lifecycle w/ expiry sweep), AllocationCycle, AgencyOrder (cyclic revision loop via recall + branching), ClientHousehold (branch on tefap_eligible + cert aging), DistributionEvent (branching pack/void/finalize)
- Calculations: 6 — fair_share_cap (threshold), tefap_income_eligibility (threshold), planned_event_poundage (forward_looking), distributed_poundage_ledger (chronological, dual-variant planned-vs-distributed), event_tefap_split (waterfall, round-per-line-then-sum), cold_storage_occupancy (aggregation)
- Validations: 14 (priority-ordered, 8 distinct categories)
- Endpoints: 40 (includes 6 FK reverse-reachability GETs + /_clock/set_current_utc test-driving endpoint)
- Errors: 15 | Roles: 4 (FoodBankOperator, AllocationManager, ComplianceAuditor = opaque; AgencyCoordinator = entity_backed:Agency) | Concurrency rules: 2 (OCC on InventoryLot.version for approve and dispose)

**Difficulty design:** 18 instances (9 rules × 2). **Corner design:** 31 instances (29 active + 2 excluded_because stubs) across all 9 taxonomy sections.

**Notable design decisions**
- Primary archetype quota_allocation + secondary ledger_reconciliation: fair-share cap competes a finite cycle pool across agencies (FEFO consumption order, weighted floor); poundage report reconciles forward-looking planned vs chronological distributed (dual-variant on same events → shrinkage_lbs).
- Flat topology (peer entities, FK links, no nested-ownership URLs) and branching state-machine shape — both under-represented/prioritized in §0.3.
- api_prefix: / (root) required: 9 distinct top-level collections, no shared prefix; setting /inventory-lots broke FK reverse-reachability for other entities.
- Two compensating-invariant pairs over different conserved quantities: lot remaining_lbs (cancel/recall release) vs order reserved-line poundage (event void revert).
- Formula-derived assertions executed in code and pinned as literals (tefap waterfall 50.00/20.00, fair-share cap 7500, TEFAP thresholds 199800/340800, capacity boundary 500).

## Step 3: Copy Shared Files — 2026-06-06T11:01:10.000Z

Copied root INSTRUCTION.md → workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-06-06T11:06:28.000Z

Output: workspace/PRD.md (247 lines, 37796 bytes). Withheld-file confirmation: did NOT read/grep/reference SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml; only SCAFFOLD.yaml + skill spec + reference examples read.

**PRD section structure:**
- §1 Introduction — 3 paragraphs (cold chain, fair allocation, FEFO, dual-ledger reporting)
- §2 Global Specifications — 2.1 RBAC (4 roles; 3 opaque, AgencyCoordinator entity-backed:Agency), 2.2 response envelope, 2.3 Pagination, 2.4 Common Resource Properties (PoundageReport common_fields:false → id+created_at only), 2.5 Cold Chain/Capacity/Occupancy, 2.6 Hierarchical Consistency + Nested Retrieval, 2.7 OCC on Inventory Lots, 2.8 Poundage Precision & Monetary Units, 2.9 Test-Driving Clock
- §3 Business Logic — 3.1 warehouse stocking + lot lifecycle, 3.2 agencies/households, 3.3 TEFAP eligibility + certification, 3.4 cycles + fair-share cap, 3.5 submit/approve + FEFO reservation, 3.6 recall/cancel + conservation invariant, 3.7 distribution events (plan/pack/finalize/void), 3.8 TEFAP split waterfall, 3.9 poundage reporting (planned vs distributed ledgers)
- §4 Endpoint table (40 endpoints, all at root since api_prefix is /)
- §5 Error catalogue (15 error IDs)

**Information-scattering decisions:** expected_lot_version OCC split across §2.7/§3.1/§3.5; cold-chain+capacity principle §2.5 with params in §3.1; TEFAP income constants in §3.3 with dollar restatement; fair-share floor rounding §3.4 + general 2dp rule §2.8 (combine); planned-vs-distributed + shrinkage_lbs deferred to §3.9.

**Contract reports:** Contract 1 (Field-Name Coverage) 47/47 PASS; Contract 2 (Rule Coverage) PASS; Contract 3 (§3 Path Purity) PASS.

## Step 5: Generate Unit Tests — 2026-06-06T11:23:19.000Z

test_helpers/ (9 files): types.py (12 enums + role enum + TypedDicts for all 9 entities; PoundageReport carries only id+created_at+computed, common_fields:false), api_client.py (37 endpoints incl _clock/set_current_utc), api_errors.py (15 error IDs + HTTP status map), assertions.py, factories.py, constants.py (TEFAP threshold helper), test_users.py (3 opaque roles + entity-backed AgencyCoordinator), fixtures.py (composite scenarios), __init__.py.

test_suite/ (conftest + 7 files, **65 tests**):
- Queue A (Difficulty): 36 tests — all 18 instances covered by exactly 2 tests each (audit: all >=2). Covers dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check (X/X+1), cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.
- Queue B (Corner): 29 tests — all 29 non-stub instances covered (all >=1).

Skips: 2 corner stubs NOT translated (correct) — errors/tefap_line_blocked_for_ineligible_household and errors/cold_storage_capacity_exceeded_alone; both excluded_because cross-refs resolve to real difficulty instances. No design instances skipped for PRD-coverage gaps — every non-stub instance passed the two-condition PRD-first filter.

Verification: 65 tests collect cleanly; coverage audit 18/18 Difficulty ≥2, 29/29 Corner ≥1, 0 bad/dual/untagged tags; all 119 PRD citations verified verbatim (fixed 2 C1/C3 paraphrase/ellipsis violations in this pass); no scaffold/§1.x/test_recipe leakage; no skip/xfail.

Notable: dual_variant_calc/poundage_ledger_planned_vs_distributed_diverge — prose narrates shrinkage=110 multi-event scenario but its assert block pins single packed-380 event (planned 380, distributed 0, shrinkage 380); translated the literal assert values per skill step-6, PRD §3.9 uniquely derives.

## Step 6: Generate Implementation — 2026-06-06T11:23:19.000Z

workspace/implementation/ (24 files): start.sh (guarded pip install + exec python3 app.py), requirements.txt (flask==3.0.3), app.py (blueprint registration, global error handlers, 0.0.0.0:$PORT default 10000), db.py (in-memory store, 8 dicts keyed by id, monotonic _seq, logical current_utc clock), errors.py (ApiError + 15-entry catalog), response.py (envelope helpers, ISO8601 3-digit ms), middleware.py (X-User-ID/X-User-Role auth, 4 roles), routes/ (9 blueprints), services/ (calc, models, validate, reservation, events, poundage).

Endpoints: 41 routes (all PRD §4 + /_clock/set_current_utc).

State machines: InventoryLot (AVAILABLE→{RESERVED,DEPLETED,EXPIRED,DISPOSED}, etc.; expiry sweep in clock route); AllocationCycle (DRAFT→OPEN freezes total_fair_share_weight over ACTIVE agencies→CLOSED gated on no SUBMITTED/APPROVED orders); AgencyOrder (SUBMITTED→{APPROVED,REJECTED,CANCELLED}, APPROVED→{SUBMITTED(recall),FULFILLED,CANCELLED}; recall/cancel release reservations, conservation verified 5000→4967→5000); ClientHousehold (PENDING→{CERTIFIED,DENIED} branch on tefap_eligible, CERTIFIED→EXPIRED 365d aging); DistributionEvent (PLANNED→{PACKED,VOIDED}, PACKED→{FINALIZED,VOIDED}; finalize = cascade origin).

Calculations: all poundage 2dp ROUND_HALF_UP via Decimal; fair_share_cap = floor(pool×weight/total_weight) int lbs; tefap_income_eligibility int cents ≤ (199800 + 70500/extra person); planned_event_poundage sums RESERVED-line reserved_lbs; event_tefap_split FEFO waterfall round-per-line-then-sum; distributed_poundage_ledger planned(PACKED+FINALIZED) vs distributed(FINALIZED only, chronological by finalized_at_seq), shrinkage = planned − distributed.

OCC: every resource has version (start 1, +1/mutation incl cascades) + updated_at; PoundageReport exempt. Two OCC-guarded writes: POST /agency-orders/{id}/approve (pins FEFO-earliest lot) and POST /inventory-lots/{id}/dispose read expected_lot_version → ERR_STALE_LOT_VERSION (412) on mismatch; absent elsewhere. Verified stale=999→412, correct→200.

Validation ordering per §4 fixed precedence: auth(401)→role(403)→agency-scope(403)→existence(404)→request/enum(422)→state(409)→cold-chain(422)→household-cert(409)→agency-suspended(409)→cycle-open(409)→capacity(409)→over-distribution(422)→fair-share(409)→OCC(412). Pagination OOB→ERR_VALIDATION_PAGINATION(422).

start.sh: cd to script dir; installs deps only if import flask fails; exec python3 app.py foreground on 0.0.0.0:$PORT (default 10000), threaded=True. Storage in-memory only, no seeding/persistence — verified fresh boot 0 entities, restart wipes state, boots ~3s. Note: a few unused imports (harmless).

## Step 7: Run Tests and Iterate — 2026-06-06T11:32:54.000Z

**Iterations run:** 2 (initial sweep surfaced 6 deterministic failures; second sweep after fixes was clean — all 8 rounds 62/62). The 6 failures were identical across all 8 rounds (no flakiness). Resolved into 2 implementation bugs, 1 test-setup bug, and 3 tests asserting a PRD-unreachable state (deleted). Orchestrator independently re-ran the 8-round parallel sweep post-exit: all 8 rounds passed=62 total=62 failed=0, union of failing tests = NONE.

### Tests deleted (3) — PRD-unreachable-state / unique-derivability collapse
All three required POST /allocation-cycles/{id}/close to succeed while a SUBMITTED order existed in the cycle. PRD §3.4: close "permitted only when no AgencyOrder in the cycle is still in SUBMITTED or APPROVED status." Faithful impl correctly rejects that close (passing test test_cycle_close_blocked_while_order_unresolved asserts this). The precondition these tests need — a SUBMITTED order in a non-OPEN cycle — is structurally unreachable (cycles only DRAFT→OPEN→CLOSED; submit requires OPEN; close requires no open orders). So ERR_CYCLE_NOT_OPEN on approve cannot be reached without violating a PRD-required check. The scaffold scenario recipe baked in this contradiction.
- test_cycle_not_open_beats_fair_share_on_approve (test_03) — scaffold rule priority_pair_validation_conflict/cycle_not_open_beats_fair_share_on_approve; unreachable-precondition (requires violating PRD §3.4 close-gating).
- test_cycle_not_open_beats_fair_share_order_unchanged (test_03) — same scaffold rule; same unreachable precondition.
- test_approve_blocked_when_cycle_closed (test_03) — scaffold rule cross_entity_state_dependency/order_approve_requires_cycle_open; same unreachable precondition.

### Fixes applied to test_helpers / test_suite (1)
- test_suite/test_06_validations_rbac.py, test_agency_suspended_blocks_order_submission — setup suspended its only agency then called create_open_cycle(), which PRD §3.4 forbids ("opening requires at least one ACTIVE agency") → setup died with ERR_INVALID_STATE. Added a second ACTIVE agency before opening the cycle so the open precondition holds; the suspended-agency assertion is unchanged.

### Fixes applied to implementation (2)
- workspace/implementation/services/events.py, planned_event_poundage() — now sums reserved_lbs over both RESERVED and SHORT lines. PRD §3.7 prose: "a SHORT line contributes only its reserved amount"; prior code counted RESERVED only, yielding planned_lbs=0 for a short-only pack. (Fixes test_pack_planned_lbs_uses_reserved_not_requested_on_short_line.)
- workspace/implementation/services/models.py + routes/households.py, certify handler — certified_at now stamped from logical "current UTC" clock (new current_clock_iso() helper reading db.current_utc) instead of wall-clock now_iso(). PRD §2.9 establishes the logical clock that drives certification aging; wall-clock stamp left certified_at off that timeline so the 365-day aging sweep never fired. (Fixes test_certification_expires_after_365_days_on_clock_advance.)

No PRD-required implementation checks were weakened; storage remains in-memory only; no new endpoints/fields/side-effects added. Final test count: 62 (was 65, −3 deleted).

## Step 8: Finalize PRD — 2026-06-06T11:36:00.000Z

PRD.md 247 lines → PRD_FINALIZED.md 247 lines (0% line-count delta; 2 lines revised in place, no lines added/removed).

**Changes:**
- §3.3 (Certification) — revise — pinned certified_at to be stamped from the logical "current UTC" clock of §2.9 (the same clock the aging sweep measures against), not wall-clock — routes/households.py:87 (models.current_clock_iso()).
- §3.7 (Packing) — revise — widened planned-poundage sum from "lines whose line_status is RESERVED" to "RESERVED or SHORT", and made explicit that only RESERVED lines are marked PACKED while a SHORT line keeps its SHORT status — services/events.py:28 + routes/events.py:124-125.

**Pre-edit search log (NO-NEW-MISMATCH):**
- Edit 1 (certified_at clock): enumerated routes/households.py:87, services/models.py:50-59 (current_clock_iso reads db.current_utc), routes/clock.py:44-50 (aging compares certified_at+365d vs logical clock); confirmed created_at/updated_at/api_request_timestamp/poundage-report created_at all keep wall-clock now_iso(). Scoped wording strictly to certified_at so it doesn't bleed into §2.4 general timestamps.
- Edit 2 (pack planned-poundage line set): enumerated services/events.py:28 ({RESERVED,SHORT}), routes/events.py:124 (planned_lbs), routes/events.py:125 (marks only {RESERVED} PACKED), services/events.py:35 (order_has_tefap_reserved_line checks {RESERVED} TEFAP gate), events.py:49/82 (TEFAP split + finalize deplete on {PACKED}), routes/events.py:164 (void reverts {PACKED}→RESERVED). Re-scoped marking clause so edit doesn't imply SHORT lines are PACKED/depleted/counted-in-TEFAP-split/reverted.

**No PRD edit needed:** 3 deleted tests (PRD-unreachable state already determined by §3.4 close-gating + §3.5 open-cycle req) and the 1 test-setup fixture fix (§3.4 already requires ≥1 ACTIVE agency to open) trace to behavior PRD already pins. The planned_event_poundage bug was an impl-vs-PRD mismatch where PRD prose was internally contradictory (RESERVED-only clause vs trailing SHORT clause) — Edit 2 resolves toward impl.

## Step 9: Complete PRD — 2026-06-06T11:45:19.000Z

Produced workspace/PRD_COMPLETED.md by copying PRD_FINALIZED.md and applying 16 minimal in-paragraph revisions. No new sections, no new lines, tables untouched.

Line counts / char-delta: PRD_FINALIZED.md = 247 lines / 37994 chars → PRD_COMPLETED.md = 247 lines / 41824 chars (+3830 chars).
Counts: 13 ambiguity-pins, 3 mismatch-revisions.

**Changes:**
- §2.3 Pagination — insert — ambiguity — non-integer limit/offset also rejected with ERR_VALIDATION_PAGINATION — services/validate.py:106-118
- §2.3 Pagination — insert — ambiguity — list endpoints accept exact-match scalar filters; unknown value → empty page; filter applied before pagination — routes/inventory.py:109, agencies.py:64, events.py:90, cold_storage.py:70, cycles.py:99
- §3.1 Intake — revise — mismatch — unit_cost_cents NOT coupled to source_type; recorded verbatim for any source, defaults to 0 — routes/inventory.py:59
- §3.3 Certification — insert — ambiguity — certify of non-PENDING household → ERR_INVALID_STATE — routes/households.py:83-84
- §3.3 Certification — insert — ambiguity — certified_at internal only, not in serialized representation — services/models.py:201-212
- §3.4 Cycle open — insert — ambiguity — both open preconditions (not DRAFT / no ACTIVE agency) → ERR_INVALID_STATE — routes/cycles.py:61-65
- §3.4 Cycle close — insert — ambiguity — close invalid-state → ERR_INVALID_STATE — routes/cycles.py:77-87
- §3.5 Order submit — insert — ambiguity — lines must be present/non-empty/array of objects else ERR_INVALID_REQUEST — routes/orders.py:82-88
- §3.5 Approval (FEFO) — insert — ambiguity — line with no matching lot reserves nothing (reserved_lbs 0, reserved_lot_id null), marked SHORT — services/reservation.py:86-88
- §3.5 Approval OCC — insert/revise — ambiguity — expected_lot_version always required (ERR_INVALID_REQUEST if absent/non-int); OCC skipped when no matching lot → approval proceeds reserving nothing — routes/orders.py:155, 181-184
- §3.5 Approval state — insert — ambiguity — non-SUBMITTED approve → ERR_INVALID_STATE, before standing/openness/fair-share/OCC — routes/orders.py:158-159
- §3.5 Reject — insert — ambiguity — non-SUBMITTED reject → ERR_INVALID_STATE; no standing/openness check — routes/orders.py:199-200
- §3.6 Recall — insert/revise — ambiguity+mismatch — recall not-APPROVED/packed-event → ERR_INVALID_STATE; release restores each line's whole reserved_lbs to the single recorded reserved_lot_id — routes/orders.py:211-214, services/reservation.py:99-119
- §3.6 Cancel — insert/revise — ambiguity+mismatch — cancel invalid-state → ERR_INVALID_STATE; same single-lot restoration — routes/orders.py:230-235, services/reservation.py:103-115
- §3.7 Pack/Finalize/Void — insert — ambiguity — pack non-PLANNED/order-not-APPROVED → ERR_INVALID_STATE (event check first); finalize missing/negative actual → ERR_INVALID_REQUEST before state, non-PACKED → ERR_INVALID_STATE; void non-PLANNED/PACKED → ERR_INVALID_STATE — routes/events.py:108-114, 143-144, 160-161
- §4 Validation order — insert — mismatch — agency-scope checked only against an already-resolved resource, so unresolvable path-id/body-FK → ERR_NOT_FOUND even when scope would also fail — routes/orders.py:70-79, households.py:28-31, events.py:48-59

Tests used only as auxiliary cross-reference; implementation was sole alignment authority.

---

## PIPELINE COMPLETE — 2026-06-06T11:45:19.000Z

All 9 steps finished. Final state: 62 tests, all passing across an independently-re-verified 8-round parallel stability sweep (8/8 rounds 62/62, zero failures, zero flakiness). Artifacts present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/ (9 files), test_suite/ (conftest + 7 files), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ + results.1..8.json}.
