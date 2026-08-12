## Step 1: Create task directory — 2026-08-11T13:35:00.000Z

Task directory pre-assigned by runner (no auto-index scan performed): `tasks/task_1184_feed_mill_operations_ration_formulation/` with `workspace/` subdirectory already present. Scenario: "Feed Mill Operations & Ration Formulation (commercial feed mill): least-cost ration formulation by nutrient constraint, ingredient inventory & bin assignment, batching accuracy & sequencing to avoid carryover, medicated feed control & flushing record, delivery scheduling & bulk truck compartments, custom-mix customer order & pricing, quality sampling & retain, ingredient price volatility & contract coverage". Difficulty parameter: "generate task hard than expert level!" — passed through to Step 2 scaffold generator only.

## Step 2: Generate scaffold — 2026-08-11T14:45:00.000Z

**Task**: `task_1184_feed_mill_operations_ration_formulation` — scaffold generated harder-than-Expert per the difficulty parameter.

**Artifacts** (all exist, non-empty, parse cleanly):
- `SCAFFOLD.yaml` (92 KB; §1.0–§1.7, no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (99 KB; single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (120 KB; single key `scaffold_corner_design`)

**Counts**: 15 entities, 70 endpoints, 37 error codes, 13 state machines, 15 calculations, 10 priority-ordered validation tiers, 5 roles, 2 OCC concurrency rules. §1.8: 19 instances (9 rules ≥2 each). §1.9: 45 active instances + 4 excluded-because stubs across all 9 guide sections; 937 total calls lint-scanned.

**Archetype & layers**: primary `compliance_audit` × secondary `quota_allocation`; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, version_pinning_on_approval. Flat topology (all resources top-level under `/api`, FK-linked), cyclic state-machine shape, `segregation_of_duties` role model (flush recorder ≠ verifier; entity-backed Operator/QualityTech via Employee.capability), immediate consistency.

**Nine-rule instance design** (each differentiated as §0.5 requires):
1. dual_variant_calc — Order quoted-vs-final pricing (426420 vs 439121 after a late price tick) × sample as-fed vs dry-matter assay (18.72 fails / 19.50 passes)
2. combinatorial_formula — mode (a) greedy optimizer with nested min(70, remaining) clamps × mode (b) pinned per-weighment rounding (3660 vs forbidden 3661)
3. non_linear_state_machine — Batch MIXED→HOLD→BATCHING rework cycle × Order CONFIRMED→REVISING→CONFIRMED repricing cycle
4. transitive_cascade — sample FAIL→Batch HOLD→order blocked→trips CANCELLED (depth 3) × weighment→contract consumed→EXHAUSTED→formula recompute→quote_stale (depth 4), different triggers
5. priority_pair_validation_conflict — state-beats-safety (cancelled batch + flush due) × safety-beats-fiscal (no medicated permit + over credit)
6. boundary_precision_check — deviation exactly 2.00% passes on /mix × protein exactly at min on /optimize + /activate
7. cross_entity_state_dependency — Batch→FlushRecord (verified flush gates non-medicated start) × DeliveryTrip→Order (load requires COMPLETED)
8. resource_temporal_overlap — Truck pure half-open (adjacency allowed) × ProductionLine 45-min buffer-extended (adjacency rejected); contract closed-date overlap as third corner
9. compensating_invariant — 3 instances: bin physical tons, customer credit cents, contract coverage tons (weigh+void / confirm+cancel restore exactly)

**Notable design decisions**: orders pin formula version + lines + nutrient floors at CONFIRM (batches consume the snapshot, so re-optimization never corrupts live orders); quote_stale is a pure derived field (version or cost-basis mismatch); contract selector is use-it-or-lose-it with full-coverage-only selection (remaining == actual selects and exhausts); logical clock with fixed default 2026-05-01T00:00:00Z drives expiry sweeps and price resolution; OCC sanctioned on Customer.version (order create) and Formula.version (optimize); every assert literal was pre-computed and verified with Python (Decimal, round_half_up).

**Lint**: `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (One FK_REVERSE_UNREACHABLE for `FlushRecord.flush_material_ingredient_id` was found and fixed by adding the filter to `GET /api/flush-records`; re-run clean.)

**Self-audits**: no forbidden concurrency vocabulary; instance names unique across both files (68); all 37 error codes referenced by validations/transitions and exercised in design files; all stubs resolve to real §1.8 instances; all tie-breaks use created_at, never id.

## Step 3: Copy shared files — 2026-08-11T14:46:00.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md (build contract: start.sh + $PORT/0.0.0.0/foreground).

## Step 4: Generate PRD — 2026-08-11T15:10:00.000Z

PRD generation complete. Output verified at `workspace/PRD.md` — 357 lines, ~8,300 words, 58,673 bytes, ending at §5 with no audit footer.

**Section structure**
- §1 Introduction — 2 paragraphs, business-context angle (margin volatility + regulatory perimeter), persona roll-call.
- §2 Global Specifications — 11 subsections: 2.1 Roles/RBAC (opaque `MillManager`/`Nutritionist`, entity-backed `Employee` for `Operator`/`QualityTech` with `OPERATOR`/`QUALITY_TECH`/`DUAL` capability gating, entity-backed `Customer` with own-resource scoping), 2.2 Response Structure (verbatim block, byte-identical), 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, 4 meta fields), 2.4 Identity/Timestamps/Versioning (incl. `PriceTick` as the `common_fields: false` exception — `id` + `created_at` only), 2.5 Logical Mill Clock (default 2026-05-01T00:00:00Z, `to_iso8601`/`current_utc`, EXPIRED sweep), 2.6 OCC (both rules, 412s, no race framing), 2.7 Monetary Precision & Rounding (integer cents, per-weighment pinned rounding, no retroactivity), 2.8 Spot Pricing & Contract Coverage (shared selector pool/ranking), 2.9 Medicated Governance & SoD, 2.10 Credit Exposure, 2.11 Validation Order of Evaluation (all 10 layers in priority order, priority-9 internal order enumerated, fiscal last).
- §3 Business Logic — 9 subsections grouped by business-process timeline: ingredients/ticks, contracts, bins, formulation/optimizer, customers/orders/credit, batching/weighments, medicated flush control, quality sampling/release, fleet/trips.
- §4 Endpoint table — 69 rows, 4 columns (Method, Path, Description, Authorized Role(s)).
- §5 Error catalogue — 37 rows, 2 columns (Error ID, HTTP Status Code), no trigger conditions.

**Zero-Silence Rule self-audit (Contract 2)** — PASS. Every scaffold behavior rendered as prose: all 14 state machines (every transition's from/to, preconditions paired with their error IDs, side effects including cascades and version bumps); all 15 calculations as precise natural language (optimizer waterfall with 70% cap and tie-breaks, contract-blend projection with no cross-line netting, pinned 7-step order pricing with both quoted/final variants, dry-matter assay adjustment with equality-passes boundaries, all four window-conflict algorithms with their boundary rules); all 10 validation layers with explicit ordering; both OCC rules with endpoint + field + error ID + 412; every cross-entity cascade (discontinue → bins/formulas, contract exhaustion → quote_stale, sample FAIL → HOLD → blocked → trip cancellation, void → bin/contract restoration); field defaults explicitly stated (null pinned fields, null `final_total_cents`, null `verified_at`, false `is_flush_material`, null `medicated_permit_ref`); sibling branches rendered with equal density (4 contract transitions, 3 cancel branches, PASS/FAIL, verify/reject).

**Hard-contract mechanical audit** — all PASS: Contract 1 (89/89 entity fields + 56/56 endpoint input identifiers present in backticks; verified by YAML-parsed diff script), Contract 3 (601 §3 backtick tokens scanned, zero paths/methods), §2.2 verbatim match, no pseudocode operators, no fuzzy words, all 37 error IDs in §2/§3 narrative, all 34 state values and all field enum values present.

**Information-scattering approach** — business-timeline grouping across 9 §3 subsections; cross-cutting concerns (selector policy in §2.8, credit in §2.10, validation order in §2.11) referenced from workflow narratives; endpoint inputs split across subsections (e.g., `actual_tons` spans §3.2/§3.3/§3.6; `tons` spans §3.5/§3.9; OCC fields span §2.6/§3.4/§3.5); constants converted for inference difficulty ($5,000/$20,000 margin tiers, $15.00/ton surcharge, $75.00 + $9.00/ton delivery, "half a ton" flush minimum, "seventy percent" inclusion cap) while preserving exact reconstruction semantics; relationships implied through actions ("payload naming the `ingredient_id`") rather than declared FKs.

**Notable decisions** — 422 errors labeled "Unprocessable Content" (scaffold gives no label text); dollar conversions used only for order-price constants, with boundary inclusivity ("at or below", "exactly 0.02 passes", "exactly 2.00 percent passes", "exactly 0.5 tons passes", "equality passes") stated everywhere the scaffold pins it; §3.8 placed rework/reject with the FAIL cascade that creates HOLD, keeping the quality narrative cohesive. The forbidden `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened or referenced.

## Step 5: Generate unit tests — 2026-08-11T15:55:00.000Z

Generation complete. Summary of the delivered test suite for `task_1184_feed_mill_operations_ration_formulation`:

## Test counts
- **Queue A (Difficulty): 38 tests** — 19 instances × 2 tests each. All 19 difficulty instances passed the PRD-first filter (every asserted literal was recomputed against PRD rules and matches: 426420/439121 quote-vs-final, 19.50/5.00 dry-matter flip, corn70/wheat30 clamp at 30900, 3660 vs forbidden 3661 rounding, 510204 revision requote, 35900→36600 exhaustion cascade, 2.00%/2.01% mix boundary, etc.).
- **Queue B (Corner): 44 tests** — all 44 non-stub instances that pass the filter covered with ≥1 test each.
- **Total: 82 tests**, 15 test files + `conftest.py`.

## Instances not translated (per the Core rule — gaps stay gaps)
- **`Corner/entities/customer_computed_field_input_ignored`** — SKIPPED. It asserts a create call carrying junk `credit_used_cents: 999999` returns 201 with server-computed 0. PRD §2.11 layer 2 enumerates schema checks (required fields, types, enums, tonnages, datetimes) but never states how unknown/extra fields on a create payload are handled; a strict-schema implementer (400) and a lenient one (201/ignored) are both PRD-faithful → fails unique derivability.
- **4 `excluded_because:` stubs NOT translated** (as required): `order_moves_in_production_on_first_batch_start`, `computed_read_final_price_after_completion`, `cascade_side_effects_covered_by_difficulty`, `dual_variant_layer_covered_by_difficulty` — all four cross-references verified to resolve to real §1.8 instances that own the assertions.

## Verification results (all automated)
- `python3 -m py_compile` on all 25 files: **OK**.
- `python3 -m pytest test_suite/ --collect-only -q`: **82 tests collected**, no import errors.
- **Design-tag audit**: all 82 tests carry exactly one `Design: <queue>/<rule|section>/<instance>` line as the docstring's last line; all tags resolve to real yaml instances; difficulty coverage ≥2, corner coverage ≥1; no stub translated; no dual/untagged tests.
- **PRD citation audit**: 135 `PRD §x.y: "..."` citations extracted and every one greps **verbatim** in `workspace/PRD.md` (whitespace-normalized). Four endpoint-table citations initially failed C1 and were rewritten to rule-bearing §2.1/§2.11 prose.
- **Hygiene**: zero "scaffold" mentions in generated code; zero `skip`/`skipif`/`xfail` markers.
- Absolute-version assertions were deliberately avoided (PRD never pins the initial `version` value); OCC/pinning tests assert relative increments (+1 per mutation, per PRD §2.4) and dynamically captured pin values.

## File layout
- `test_helpers/` — `types.py` (15 entity TypedDicts; PriceTick correctly omits `updated_at`/`version` per PRD §2.4), `api_client.py` (66 endpoint methods covering the full §4 catalogue), `api_errors.py` (37 error IDs + HTTP map registered with the framework), `assertions.py`, `factories.py`, `constants.py` (PRD thresholds incl. 45-min buffer, 2.00% tolerances, margin tiers, $15/$75/$9 pricing constants), `test_users.py` (opaque shared constants + per-instance builders for the three entity-backed roles), `fixtures.py` (composite scenarios: confirmed order → batching → mixed → released → completed; medicated contaminated-line environment with the critical optimize-before-med-tick ordering; stocked bins; OCC-safe order creation).
- `test_suite/` — `test_01_entity_basics`, `test_02_envelope_and_listing`, `test_03_optimizer_and_nutrients`, `test_04_pricing_and_quotes`, `test_05_credit_and_revisions`, `test_06_batching_and_weighments`, `test_07_quality_and_release`, `test_08_cascades`, `test_09_flush_and_contamination`, `test_10_delivery_and_fleet`, `test_11_order_completion`, `test_12_bin_contract_admin`, `test_13_validation_layers`, `test_14_rbac`, `test_15_concurrency`.

One latent design-index quirk worth noting (not a test bug): `Corner/calculations/contract_selector_use_it_or_lose_it_ordering` sets C2's window to start 2026-06-01, which is after the default clock (2026-05-01), so C2 is not actually in the pricing pool at weighment time — the emitted test's asserted literals (C1 selected at 29500, C2 untouched) remain PRD-derivable and correct regardless.

## Step 6: Generate implementation — 2026-08-11T15:55:00.000Z

Implementation complete. Summary:

## File layout
`workspace/implementation/` (~98 KB total):

| File | Size | Role |
|---|---|---|
| `start.sh` (executable) | 389 B | Guarded launcher: `python3 -c "import flask"` check before any pip install, then `exec python3 app.py` |
| `requirements.txt` | 11 B | `flask>=2.2` |
| `app.py` | 1.2 KB | Entry point; binds `0.0.0.0:$PORT` (default 10000); envelope-wrapped 404/405/500 handlers |
| `db.py` | 1.7 KB | In-memory STORE (15 entity tables, empty at boot, no seeding), logical clock (fixed default `2026-05-01T00:00:00Z`), UUID/timestamp/version-bump helpers |
| `errors.py` | 367 B | `ApiError(error_id, http_status, message)` |
| `envelope.py` | 1.4 KB | PRD §2.2 envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), Decimal-aware JSON provider |
| `middleware.py` | 1.5 KB | Auth (`X-User-ID`/`X-User-Role`, 5 roles) + RBAC incl. entity-backed capability gate (OPERATOR/QUALITY_TECH/DUAL) |
| `validation.py` | 4.9 KB | Schema layer (types, enums, tons>0, datetime/date parsing, end>start), pagination (limit 1–100 default 10, offset, has_more) |
| `services.py` | 23 KB | All calculations + cascades + serializers |
| `routes/` (15 modules) | ~57 KB | One module per resource group |

## Endpoint coverage
**70 (method, path) pairs registered — exactly matches SCAFFOLD.yaml §1.5's 70-entry endpoint table** (verified programmatically via Flask's url_map). Orchestrator independently re-verified post-hoc: normalized url_map diff vs scaffold = 0 missing, 0 extra (only artifact is Flask's built-in /static rule; impl uses named converters <bid>/<oid> where scaffold writes {id}).

## Smoke-test results (server launched via `bash start.sh` on a scratch port, killed after)
- **Smoke 1 (76 checks, all PASS)**: unauthenticated 401 envelope; employee/ingredient/tick/contract/bin/customer/formula/order/batch/weighment/sample/flush/line/truck/trip create+get+list; duplicate-code 409; OCC 412 on both `expected_customer_version` and `expected_formula_version`; optimizer waterfall (70/30 cheapest-first) with hand-verified nutrient totals (9.55/4.25/2965) and provisional cost (20100); contract creation recompute (19200); closed-interval contract overlap 409; quoted price hand-verified (231540 = 192000 + 12% margin + 16500 delivery); confirm pins formula v3 + credit charge; line-window 45-min buffer conflict (and buffer-adjacent allowed); capability 403; batch start → order IN_PRODUCTION; bin-ingredient mismatch 422; CONTRACT vs SPOT weighment sourcing with per-weighment rounding; mix; dry-matter PASS (9.2 as-fed @8% moisture → 10.00); release; complete → final price equality (231540) + credit reclass; trip load/depart/deliver → order auto-DELIVERED with credit release; pagination meta; clock advance → contract EXPIRED sweep; sample FAIL → HOLD → order blocked → rework unblock.
- **Smoke 2 (25 checks, all PASS)**: fresh-boot empty store (per-test-server isolation); ERR_MEDICATED_PERMIT_REQUIRED; ERR_CREDIT_LIMIT_EXCEEDED (402); line contamination MEDICATED after medicated mix; ERR_FLUSH_REQUIRED gate (unverified flush insufficient); verified flush after clock advance clears contamination; contract exhausted at exact-zero boundary → void reopens to OPEN and restores bin; ingredient-discontinue cascade (bin BLOCKED, unblock); Customer-role foreign-order 404.

## Notable design decisions
- **State machines**: statuses stored, but derived flags (`Bin.status` via `blocked` flag + on_hand, `contamination`, `blocked`, `quote_stale`, `credit_used_cents`, `on_hand_tons`, `consumed_tons`, batch `actual_tons`/`ingredient_cost_cents`) are computed at read time per PRD's "immediate" consistency — cascade flips (READY↔EMPTY, OPEN↔EXHAUSTED, EXPIRED sweep) detected by before/after comparison so version bumps fire exactly once per transition.
- **Calculations**: everything in `Decimal`, round-half-up only; per-weighment rounding pinned before summation; provisional cost rounds once at the end; quoted price follows the pinned 7-step evaluation (line costs rounded per line → subtotal → tier on pre-margin subtotal → margin → surcharge → delivery); contract pool ranked window_end ASC / price ASC / created_at ASC; weighment selector is all-or-nothing (`remaining_tons >= actual_tons`, boundary selects and exhausts).
- **OCC**: `expected_customer_version` (order create, customer PATCH) → ERR_STALE_CUSTOMER_VERSION 412; `expected_formula_version` (optimize) → ERR_STALE_FORMULA_VERSION 412; both required (missing → 400), checked at layer 5, after existence, before state.
- **Clock**: single logical clock drives all domain timestamps (`created_at`, `mixed_at`, `verified_at`, price effectiveness, contract windows, retain expiry); wall clock used only for the `meta.api_request_timestamp`; expiry sweep runs on clock-set and lazily on contract reads.
- **Validation ordering**: strict PRD §2.11 layering in every handler — auth(401) → schema(400) → RBAC+capability(403) → existence left-to-right with Customer-ownership-as-404(404) → OCC(412) → state(409, incl. ERR_BIN_BLOCKED/ERR_ORDER_BLOCKED) → safety(422/409) → temporal windows(409) → constraints in the PRD's listed order (compartment capacity before order over-allocation) → fiscal last (ERR_QUOTE_STALE 409 before ERR_CREDIT_LIMIT_EXCEEDED 402).
- **Version discipline**: bumps only where the scaffold/PRD declares mutations (transitions, explicit side effects, PATCH/assign/replenish); provisional-cost recomputation never bumps `Formula.version`, per PRD 3.4.

## Step 7: 8-round sweep iterate-to-pass — 2026-08-11T16:15:00.000Z

**Iteration 1** (8 parallel rounds, `sweep.sh`): every round 79/82 — identical failure set in all 8 (no flakiness):
1. `test_06_batching_and_weighments.py::TestImmediateConsistency::test_immediate_consistency_weighment_response_and_bin_read` — asserted `bin.version` bumps +1 after a weighment. Diagnosis (STEP 1b/1c): PRD §3.3 defines `on_hand_tons` as a conservation-law derivation and bin status derivation as "mechanical"; PRD names bin version increments only at replenish (§3.3) and cascade-block (§3.1), names none at weighment-record/void (§3.6), and §3.4 explicitly states recomputation never increments version — so "weighment bumps bin version" is not uniquely derivable (two faithful readings exist). Fix: removed the single version assertion (kept PRD-covered per-weighment pricing + immediate `on_hand_tons` deduction assertions).
2. `test_10_delivery_and_fleet.py::TestTripLoadGate::test_trip_load_rejected_while_order_in_production` — NameError: `setup_batching_batch` used but not imported. Test bug (STEP 2); rule itself (§3.9 load requires COMPLETED) is PRD-verbatim. Fix: added `setup_batching_batch` to the `from test_helpers import (...)` list.
3. `test_10_delivery_and_fleet.py::TestTripLoadGate::test_trip_load_succeeds_after_order_completed` — same missing import, same fix.

**Fixes applied**: `test_suite/test_06_batching_and_weighments.py` (one underivable assertion removed; no test deleted), `test_suite/test_10_delivery_and_fleet.py` (import list). No `test_helpers/` changes. No `implementation/` changes. No PRD changes.

**Iteration 2** (8 parallel rounds): all 8 rounds 82/82 passed, 0 failed. Exit condition met.

## Step 8: Finalize PRD — 2026-08-11T16:35:00.000Z

Done. `workspace/PRD_FINALIZED.md` written. (Step 8 NOT skipped: Step 7 took 2 iterations with 2 `test_suite/` fixes, one of which — the bin-version-on-weighment assertion removal — revealed a genuine PRD silence.)

**Line counts / delta:** PRD.md 357 lines, PRD_FINALIZED.md 357 lines (0% line delta; one in-place sentence insertion in §3.3, +116 words on line 160).

**Changes:**
- §3.3 (Bin Assignment and Inventory Conservation) — insert — added: "Recording or voiding a weighment changes only derived bin state, so the bin's `version` is left untouched by those events unless the derived status actually flips: the `READY` → `EMPTY` flip on a drawdown to exactly zero and the `EMPTY` → `READY` flip when a void restores stock to an empty bin each increment the bin's `version` by one, while a drawdown or restoration that leaves the status unchanged does not." — pins the impl's conditional bump at `implementation/routes/batches.py:159-162` (record) and `implementation/routes/weighments.py:56-63` (void).

The other Step 7 item (missing `setup_batching_batch` import in test_10) is a pure test-fixture bug with no PRD implication — no edit made.

**Per-edit pre-edit search log:**
- Edit 1 (Bin.version on weighment record/void):
  - (a) Subject: whether Bin `version` increments when a weighment is recorded against or voided from that bin.
  - (b) Enumerated impl paths touching Bin state/version: `routes/bins.py:63-77` (assign — stored-field mutation, unconditional `bump`, bins.py:76); `routes/bins.py:80-96` (replenish — stored-field mutation, unconditional `bump`, bins.py:95, already PRD-pinned in §3.3); `routes/bins.py:99-111` (unblock — stored-field mutation, unconditional `bump`, bins.py:110); `routes/batches.py:110-165` (record_weighment — no stored bin field changes; `bump(bin_rec)` only inside `if bin_status(bin_rec) != before` at batches.py:161-162); `routes/weighments.py:44-69` (void_weighment — same conditional flip-bump at weighments.py:62-63); `services.py:369-374` (discontinue cascade — stored `blocked=True`, unconditional `bump`, PRD-pinned §3.1); `services.py:55-64` (`bin_on_hand`/`bin_status` are pure derivations — confirms weighment events mutate no stored bin field). Full-store grep for `STORE["bins"]` confirmed no other writers (flushes/samples/trips/trucks/orders/clock never touch bins).
  - (c) Wording scoped explicitly to "Recording or voiding a weighment" so it cannot be read as weakening the pinned replenish increment (§3.3), the §3.1 cascade-block increment, or §2.4's blanket rule for genuine stored-field mutations (assign/unblock); phrased as "changes only derived bin state" to reconcile with §2.4 rather than contradict it.

## Step 9: Complete PRD — 2026-08-11T17:00:00.000Z

Done. `workspace/PRD_COMPLETED.md` produced as a minimal patch over the finalized PRD, with every divergence found by an exhaustive walk of `implementation/` pinned inline.

**Size delta**
- Source `PRD_FINALIZED.md`: 357 lines, 59,090 chars
- `PRD_COMPLETED.md`: 360 lines, 62,901 chars (+3 lines, +3,811 chars; 24 diff hunks, all in-paragraph inserts/revisions plus two bullets in §2.2 and one table row in §5 — no new sections)

**Counts**
- Ambiguity pins (PRD silent → inserted what impl does): 27
- Mismatch revisions (PRD wording contradicted impl → revised): 2

**Changes**
- §2.1 — insert — ambiguity — X-User-ID not resolving to a registered Employee fails the floor-role capability gate with ERR_FORBIDDEN — implementation/middleware.py:30-39
- §2.2 — insert — ambiguity — envelope `api_request_timestamp` reads the wall clock, not the logical mill clock — implementation/envelope.py:21-25
- §2.2 — insert — ambiguity — unknown path / unsupported method → ERR_NOT_FOUND (404) in the error envelope; unhandled fault → ERR_INTERNAL (500) — implementation/app.py:25-36
- §2.3 — insert — ambiguity — limit below 1 clamped to 1, negative offset clamped to 0, non-integer limit/offset → ERR_INVALID_REQUEST — implementation/validation.py:146-163
- §2.3 — insert — ambiguity — list ordering ties on `created_at` break toward earliest creation sequence — implementation/services.py:45-48
- §2.4 — insert — ambiguity — resources are born at `version` 1 with `updated_at` == `created_at` — implementation/db.py:65-74
- §2.5 — revise — mismatch — clock endpoint accepts any supplied instant, including backwards; no monotonicity check (PRD said "advances") — implementation/routes/clock.py:18-19
- §2.7 — insert — ambiguity — finer-precision tonnage inputs are rounded half-up to 3 decimals at intake; exceptions: bin `capacity_tons`, compartment `capacity_tons`, flush `quantity_tons` recorded as supplied — implementation/validation.py:89-92, routes/bins.py:30, routes/trucks.py:35, routes/flushes.py:29
- §2.11 — insert — ambiguity — body identifiers resolve in the order fields are named in the endpoint's payload (e.g. trips: truck then order; batches: order then line) — implementation/routes/trips.py:59-64, routes/batches.py:39-43
- §3.1 — insert — ambiguity — price ticks may be recorded for an ingredient in any status; only existence required — implementation/routes/ingredients.py:76
- §3.1 — insert — ambiguity — discontinuing a non-ACTIVE ingredient → ERR_INVALID_STATE — implementation/routes/ingredients.py:60-61
- §3.2 — insert — ambiguity — `window_end_date` earlier than `window_start_date` → ERR_INVALID_REQUEST — implementation/routes/contracts.py:32-33
- §3.2 — insert — ambiguity — lazy expiry also runs on contract list and before cancel processing, so a window-past contract refuses cancellation with ERR_INVALID_STATE — implementation/routes/contracts.py:71-83, 100-101
- §3.3 — insert — ambiguity — bin assignment requires ingredient existence only; the ingredient's status is not consulted — implementation/routes/bins.py:70-71
- §3.3 — insert — ambiguity — replenish on an unassigned bin → ERR_INVALID_STATE — implementation/routes/bins.py:89-90
- §3.3 — insert — ambiguity — unblock refusals (empty blocked bin, or bin not BLOCKED) → ERR_INVALID_STATE — implementation/routes/bins.py:105-108
- §3.4 — insert — ambiguity — a new formula's nutrient totals and `provisional_cost_cents_per_ton` are null and `meets_constraints` false until first optimization — implementation/routes/formulas.py:33-38
- §3.5 — insert — ambiguity — customer PATCH bumps version even when altering neither field; set-status to the already-held status → ERR_INVALID_STATE — implementation/routes/customers.py:60-68, 78-79
- §3.5 — insert — ambiguity — order create with an unregistered customer X-User-ID → ERR_NOT_FOUND — implementation/routes/orders.py:55-57
- §3.5 — insert — ambiguity — begin-revision batch-blocking violation → ERR_INVALID_STATE — implementation/routes/orders.py:145-148
- §3.5 — insert — ambiguity — commit-revision re-derives `is_medicated` from current formula lines and does not re-check the formula's status — implementation/routes/orders.py:167-181
- §3.5 — insert — ambiguity — completion requires an IN_PRODUCTION order (ERR_INVALID_STATE, evaluated before the three gates) — implementation/routes/orders.py:219-220
- §3.6 — insert — ambiguity — line set-status to the already-held status → ERR_INVALID_STATE — implementation/routes/lines.py:51-52
- §3.6 — insert — ambiguity — batch scheduling imposes no order-state precondition (a batch may be planned against a QUOTED order) — implementation/routes/batches.py:39-52
- §3.6 — insert — ambiguity — a pinned line whose rounded mix target is zero passes only when its weighed actual is also zero — implementation/services.py:289-293
- §3.8 — revise — mismatch — FAIL cascade moves the batch to HOLD only if still MIXED when the result is entered (an already-RELEASED batch stays); batch version bumps only on an actual move; trip cancellation applies regardless — implementation/services.py:382-392
- §3.9 — insert — ambiguity — trip dispatch requires the truck AVAILABLE (RETIRED → ERR_INVALID_STATE), checked before the order-state gate — implementation/routes/trips.py:66-67
- §3.9 — insert — ambiguity — allocation naming a nonexistent `compartment_seq` → ERR_INVALID_REQUEST; allocation list may be empty (zero-tonnage trip); duplicate `compartment_seq` entries allowed, each capacity-checked individually — implementation/routes/trips.py:29-44, 87-99
- §5 — insert — ambiguity — added `ERR_INTERNAL` | 500 row to the error catalogue — implementation/app.py:33-36

Everything else in the implementation (all 60 endpoints, RBAC table, state machines, pricing/optimizer formulas, window rules, cascades, OCC, validation layering, serializers) was already uniquely pinned by PRD_FINALIZED.md and left untouched.
