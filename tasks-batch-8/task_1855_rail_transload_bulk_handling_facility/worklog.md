# Worklog — task_1855_rail_transload_bulk_handling_facility

## Step 2: Generate Scaffold — 2026-08-14T21:58:00.000Z

Done. All three scaffold artifacts are generated and lint-clean.

## Deliverables (in `/home/ubuntu/github/CodingPRD/tasks/task_1855_rail_transload_bulk_handling_facility/`)

**SCAFFOLD.yaml** (1192 lines) — §1.0–§1.7 only:
- Profile: `quota_allocation` × `pricing_engine`; layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, derived_field_reconciliation; flat topology, parallel state-machine shape, peer_roles, immediate consistency
- 14 entities: Facility (config + computed safety posture), Customer (credit standing, demurrage/SIT basis variants, track-space allocation), Product (hazard class × segregation group), Track (status × derail_protection parallel dims + spot counters), Equipment (cleaning cycle + last-product provenance), SafetyIncident, Railcar (9-state placement machine × hold dimension + 4 clock timestamps), InventoryLot (SIT accrual + tonnage conservation), SpotOrder, SwitchOrder, TransferOrder (PLANNED/ACTIVE/PAUSED/SUSPENDED cycles), WeightTicket, ChargeEntry, Invoice
- 68 endpoints (incl. `POST /_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`), 34 errors, 16-priority validation ladder, 6 roles (CustomerRep is `entity_backed:Customer` with ownership scoping; rest opaque)
- 7 calculations with pinned constants: tiered marginal demurrage (48h free, 7500/15000/25000¢ tiers × hazard 1.5 × credit 1.25/1.5), SIT calendar-vs-business day counting, STRICT vs WEIGHTED contamination scoring, switching-fee allowance sequencing (spot 18500¢/pull 20500¢), cleaning fee schedule, per-line-then-sum invoice rounding, incident-count posture thresholds
- 2 OCC concurrency rules (spot-order create-with-supersede on `Railcar.version`, allocation-adjustment on `Customer.version`) — both true races per §1.2.1's serial-observability filter; plain double-spot/double-release were classified as state preconditions

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (866 lines) — 20 instances, all 9 rules ≥2, every differentiation clause on distinct domains/pairs/metrics; all formula-derived asserts are precomputed literals (e.g., 22500¢ vs 0¢ demurrage basis split; 25000¢ vs 15000¢ SIT split; invoice total 106126 with the 28126-vs-28125 rounding-trap delta; tier straddle 78750¢).

**SCAFFOLD_CORNER_DESIGN.yaml** (1221 lines) — 44 instances (38 active + 6 `excluded_because` stubs) across all nine claim-guide sections: full lifecycle walk, terminal lockdowns, every error trigger, RBAC denials (including FacilityAdmin denied under peer-role model), CustomerRep ownership scoping, both OCC stale-version tests, pagination/filtering, FK reverse lists, envelope shape, counter reconciliation, immediate consistency.

## Lint verdict (verbatim)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(68 endpoints, 14 entities, 20 §1.8 + 38 §1.9 active instances, 1087 calls scanned.)

## Key design decisions worth noting
- **Removed `ERR_LOT_INSUFFICIENT`** as unreachable: with lot on_hand always == Σ car remaining, the car-level over-delivery check strictly dominates it — the catalog stays honest (all 34 errors have at least one triggering instance, verified programmatically).
- **Spot-window overlap vs crew-buffer interaction**: same-track adjacency (`end == start`) is always dominated by the 30-min crew buffer, so the half-open-geometry proof is built around physical occupation (time-independent rejection) plus acceptance at exactly `window_end + buffer`.
- **Instance replay fixes applied during authoring**: staggered same-track spot windows in three instances (buffer conflicts), paused TO1 before the CREDIT_HOLD trigger (constraint-vs-fiscal priority masking), used a third track in the spot-gates instance (TRACK_FULL masking), clock-stepped cleaning attempts for deterministic charge ordering.
- Placeholder closure, name uniqueness (64), forbidden-vocabulary scan, enum closure, and trigger↔side-effect matching all verified clean by script.

## Step 3: Copy Shared Files — 2026-08-14T22:01:00.000Z

Copied ./INSTRUCTION.md to tasks/task_1855_rail_transload_bulk_handling_facility/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-14T22:10:00.000Z

Everything verifies. The PRD ends at §5 with no audit footer, §2.2 is byte-identical to the canonical block, all 68 endpoints and 34 errors are tabulated with correct structure.

**Summary**

Generated `/home/ubuntu/github/CodingPRD/tasks/task_1855_rail_transload_bulk_handling_facility/workspace/PRD.md` (~315 lines) from the scaffold, per the `prd-bench-doc-generator` skill. The two forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened.

**Structure**: §1 introduction (2 paragraphs, business-context angle); §2 with 9 subsections — RBAC, verbatim §2.2 response envelope, pagination, common properties + logical clock, numeric precision, facility config + safety posture, track/derail parallel dimensions, OCC, and a numbered 16-priority validation order; §3 with 8 domain-derived subsections (master data; lots/SIT; railcar registry/demurrage; spot orders/crew windows/allocation; transfer orders/contamination; weight tickets/reconciliation; cleaning/release/departure; charges/invoices/settlement); §4 endpoint table (4 columns, 68 rows); §5 error catalogue (2 columns, 34 rows).

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields + endpoints input/query/path params + occ fields: 98 required, 98 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 16-priority ordering expressed as an explicit numbered list in §2.9, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write capability + expected_railcar_version/expected_customer_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: all transitions across 13 machines expressed with from/to states, preconditions paired to error IDs, and every side-effect cascade (arrive lot-load, execute occupied/reserved counters, release PULL+demurrage+spot-close, certify triple-ledger + auto-complete + empty-car cascade, void compensation, posture suspend/resume cascade, supersede/cancel switch+charge compensation), 0 missing
- calculations[]: 7 checked (demurrage_accrual, sit_accrual, contamination_risk_score, switching_fee, cleaning_fee, invoice_total, safety_posture) — all formulas, constants (7500/15000/25000, 3/4-day tiers, 1440, 60/25/15, threshold 100, 18500/20500, 250000/600000/1200000, suspend-count 3), variants, and precision rules expressed in precise prose, 0 missing
- validations[] conditions: 34 error IDs all mentioned in §2/§3 near their triggers, 0 missing
- endpoints[].side_effects / applies_to: expressed in workflow narratives, 0 missing
- entities[].fields[] structured content: defaults, nullability, common_fields:false for SafetyIncident/SwitchOrder, computed-field derivations all stated, 0 missing
- sibling-branch symmetry: parallel branches (place/lift-hold, engage/disengage-derail, pass/fail-cleaning, REQUESTED vs SCHEDULED supersede, ACTIVE vs PAUSED complete) rendered with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 504
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 emitted byte-identical to the canonical `section-2.2-response-structure.md`; no pseudocode operators (`==`, `+=`, `>=`, …) in §3; no fuzzy words ("approximately", "about", "around" as approximation — the one "built around" false-positive was reworded anyway); all 6 role names and all 60+ state/enum values appear verbatim; PRD ends at §5 with no audit footer.

---

## Step: Unit test generation (test_helpers/ + test_suite/)

Generated per skills/prd-bench-unit-test-generator (design-index-only contract).

- test_helpers/: types.py (14 entity TypedDicts + 21 enums; SafetyIncident/SwitchOrder omit updated_at/version per PRD §2.4), api_client.py (one method per PRD §4 endpoint + /_clock/set_current_utc), api_errors.py (34 error IDs + HTTP map registered with the framework), assertions.py, factories.py, constants.py (demurrage tiers, switching/cleaning fees, posture threshold), test_users.py (CustomerRep entity-backed via make_customer_rep_headers(customer_id)), fixtures.py (primitives + setup_spotted_car / setup_active_transfer / setup_ready_for_release_car composites).
- test_suite/: 9 files, 79 test functions, all imports from test_helpers, per-test server isolation assumed.

Coverage audit (scripted):
- Queue A: all 19 difficulty instances x2 tests each — OK.
- Queue B: all 38 non-stub corner instances x1+ tests each — OK; all 6 excluded_because stubs left untranslated (cross-references resolve).
- 0 bogus tags; every docstring ends with exactly one `Design: Difficulty/...` or `Design: Corner/...` line copied from the yaml `name:`.
- PRD-citation pass (scripted): every quoted docstring span >=40 chars greps verbatim against workspace/PRD.md (whitespace-normalized) — 0 failures.
- No pytest.mark.skip / skipif / xfail anywhere.

Notable PRD-first adjudications:
- Corner/state_machines/track_and_posture_gates_on_spot_orders_rejected: the design's literal setup (three REQUESTED orders sharing cap-1 T1) contradicts PRD §3.1+§3.4 (REQUESTED orders count in reserved_spots, so the "successful" schedule would itself hit ERR_TRACK_FULL). Setup restructured onto five cap-1 tracks so each asserted gate is isolated; all asserted error IDs and the §2.9 priority claim (derail item 7 before spot-number item 10) preserved.
- Corner/endpoints/fk_reverse_reachability_lists: PRD names list filters only for equipment (§3.1 contamination-audit filter by last_product_id and status). Test asserts exactly that PRD-covered surface; the scaffold's broader per-FK filter enumeration is not PRD-derivable and was not asserted.
- Corner/cross_cutting_layers/pagination_with_filtering: limit/offset/total_count/has_more asserted per PRD §2.3; the railcar customer_id/placement_status filter-narrowing sub-claims are not named in PRD prose and were dropped.
- allocation-adjustments success validated with get_success_data (PRD §4's 201-vs-200 rule does not uniquely pin a modification-style sub-resource POST); the 412/409 error paths are status-pinned per §5.

## Step 5: Generate Unit Tests — 2026-08-14T22:42:00.000Z

Generation complete for task_1855. All artifacts written and validated.

**Stage 1 — `test_helpers/`** (9 files): `types.py` (14 entity TypedDicts, 21 enums; `SafetyIncident`/`SwitchOrder` correctly omit `updated_at`/`version` per PRD §2.4), `api_client.py` (one method per PRD §4 endpoint + `/_clock/set_current_utc`), `api_errors.py` (all 34 error IDs with HTTP map registered via `set_error_http_status_map`), `assertions.py`, `factories.py`, `constants.py` (demurrage tiers 7500/15000/25000, switching fees 18500/20500, cleaning fees, suspend-count 3, default clock `2026-08-01T00:00:00Z`), `test_users.py` (five opaque roles + `make_customer_rep_headers(customer_id)` for the entity-backed CustomerRep), `fixtures.py` (primitives plus `setup_spotted_car` / `setup_active_transfer` / `setup_ready_for_release_car` composites).

**Stage 2 — `test_suite/`**: 9 test files, **79 test functions**, all imports via `test_helpers`.

**Scripted audits, all green:**
- Queue A: all 19 difficulty instances have exactly ≥2 tests — 38 tests.
- Queue B: all 38 non-stub corner instances have ≥1 test; all 6 `excluded_because` stubs left untranslated (cross-references verified to resolve).
- Every docstring ends with exactly one `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` line copied verbatim from the yaml `name:`; zero bogus tags.
- PRD-citation pass: every quoted docstring span ≥40 chars greps verbatim against `PRD.md` (whitespace-normalized) — 0 failures.
- No `pytest.mark.skip`/`skipif`/`xfail`; full import graph loads under the installed runner package.

**Key PRD-first adjudications (documented in the task `worklog.md`):**
1. `track_and_posture_gates_on_spot_orders_rejected` had an internally inconsistent setup — three REQUESTED orders on a cap-1 track would trip `ERR_TRACK_FULL` (PRD §3.1 counts REQUESTED in `reserved_spots`) on the schedule the design expected to succeed. I restructured onto five cap-1 tracks, preserving every asserted gate and the derail-beats-spot-number priority claim.
2. `fk_reverse_reachability_lists`: PRD names list filters only for equipment (§3.1 `last_product_id`/`status` contamination-audit); the test asserts exactly that covered surface instead of the scaffold's broader per-FK enumeration.
3. `pagination_with_filtering`: pagination mechanics asserted per §2.3; railcar filter-narrowing sub-claims (not named in PRD prose) dropped.
4. Allocation-adjustment successes validated leniently (`get_success_data`) since PRD §4's 201/200 rule doesn't uniquely pin a modification-style sub-resource POST; error paths (412/409) remain status-pinned per §5.

## Step 6: Generate Implementation — 2026-08-14T22:52:00.000Z

Implementation complete and fully verified. Summary:

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_1855_rail_transload_bulk_handling_facility/workspace/implementation/` — Python + Flask, in-memory only (dicts in `db.py`, no disk/SQLite, no seeding):

- `start.sh` — guarded dependency install (no-op once Flask is importable, so per-test reboots don't re-run pip) + `exec python3 app.py`, foreground, `0.0.0.0:$PORT` (default 10000)
- `app.py` — Flask entry, global RLock per request (atomic mutations + cascades), envelope-wrapped 404/405/500 handlers
- `db.py` — store, logical clock (default `2026-08-01T00:00:00Z`, set only via `POST /_clock/set_current_utc`, never wall-clock), 3-fractional-digit ISO timestamps, `version`/`updated_at` management (SafetyIncident and SwitchOrder correctly carry only `id`/`created_at`)
- `errors.py`, `response.py` (exact `meta`/`response_type`/`data` envelope, `limit`/`offset`/`total_count`/`has_more` pagination, defaults 10/0, 1–100 clamp), `middleware.py` (X-User-ID/X-User-Role auth, 6 roles, CustomerRep entity-backed ownership), `validate.py`, `util.py` (Decimal tonnage/money, round-half-up, half-open interval math)
- `domain.py` — all 7 calculations: tiered demurrage (7500/15000/25000 over 3/4/∞ days, hazard ×1.5, credit ×1/1.25/1.5, single final round-half-up), SIT calendar/business block counting, STRICT_MATRIX/WEIGHTED_SCORE contamination scoring, switching-fee allowance sequencing (prior-count → sequence → fee; 18500/20500), cleaning fees, per-line-then-sum invoice totals, posture threshold machine with suspend/resume cascades
- `routes/` — 16 modules covering all 68 endpoints

## Key fidelity decisions (all pinned against PRD + design docs)

- **Validation ladder** (§2.9) governs cross-category ordering: verified pins include role(2)>existence(3), existence>state, shape(4)>state, posture/derail(7)>hold(8)>contamination(9)>constraints(11)>credit(12), state(5)>unpaid-invoice(13), allocation-floor(15)>OCC(16), ownership(6)>OCC.
- **TRACK_FULL** at schedule uses `occupied + scheduled_orders + 1 > capacity` — the literal `reserved_spots` counter reading is contradicted by the corner design's pinned asserts (a schedule must succeed with two other REQUESTED orders on a cap-1 track); the displayed `reserved_spots` counter still counts REQUESTED+SCHEDULED per the derived-counter pins (create +1, cancel −1, execute −1, supersede-from-SCHEDULED −1 but not from REQUESTED).
- Empty-car cascade (IN_TRANSFER→EMPTY_AWAITING_CLEANING→READY_FOR_RELEASE when `requires_full_clean=false`) fires independently of order auto-completion; both fire on the same certification when applicable.
- DEMURRAGE/SIT charges are created even at amount 0; switching charges are created at fee 0 inside the free allowance; each charge's `unit_rate_cents = amount/quantity` (0 when quantity 0).
- CustomerRep list endpoints auto-scope to own customer; explicit foreign `customer_id` filter → 403 `ERR_RESOURCE_NOT_OWNED`; lots/switch-orders/equipment etc. are deliberately not ownership-scoped per PRD §2.1.

## Verification

- 100+ behavioral checks across 41 base checks + 38 scenario groups (each against a fresh `start.sh` boot, mirroring per-test-server isolation) + 21 edge checks — all pass, including the pinned numbers: demurrage 22500 vs 0 (basis split), 78750 (tier straddle ×1.5), 14063-per-line / invoice total 106126 (round-per-line), SIT 25000 vs 15000 (calendar vs business), contamination 100-block vs 60-allow, switching sequence 0/18500/20500, invoice period inclusive bounds, supersede/cancel compensation invariants, suspend/resume depth-3 cascade, certify auto-complete cascade, certify+void exact restoration.
- Clean-boot contract confirmed: two consecutive `bash start.sh` launches each yield an empty store and the default clock — no carry-over state.

## Step 7: Run Tests and Iterate — 2026-08-14T22:58:00.000Z

All 8 rounds are green with fresh results (written 22:57, this run): 79/79 passed, 0 failed, 0 errors in every round. The exit condition — all 8 rounds with `passed == total` — is met on the first sweep, so no diagnostic or fix cycle was triggered.

**Summary**

- **Iterations run:** 1 (one 8-round parallel stability sweep; every round ran to completion, all 8 clean).
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `test_suite/`:** none.
- **Fixes applied to `implementation/`:** none.

**Notes**

- The known pre-existing TRACK_FULL tension (Step 5 tests reading PRD §3.1/§3.4 as `occupied_spots + reserved_spots` with REQUESTED orders counting, vs. Step 6 implementation's `occupied_spots + scheduled_count + 1` gate at `workspace/implementation/routes/spot_orders.py:171`) did **not** surface as a failure in any of the 8 rounds — no test in the suite constructs a scenario where the two formulas diverge (i.e., scheduling while other REQUESTED-but-not-SCHEDULED orders inflate `reserved_spots` beyond capacity), so the union-of-failures set was empty and the adjudication protocol was never triggered. Per the diagnostic protocol, fixes are only applied in response to an observed failure; the implementation and tests were left byte-for-byte untouched.
- Results verified as fresh: all 8 `results.{i}.json` files carry this run's timestamp and show `outcomes={'passed': 79}` with zero errors.

## Step 8: Finalize PRD — SKIPPED — 2026-08-14T22:58:30.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the tests exercise; no `PRD_FINALIZED.md` is produced. (Residual PRD-vs-impl divergence that tests never exercise — e.g., the TRACK_FULL gate formula noted in Step 7 — is in Step 9's scope.)

## Step 9: Complete PRD — 2026-08-14T23:12:00.000Z

PRD_COMPLETED.md is written: 320 lines / 54,243 chars vs source PRD.md 317 lines / 50,049 chars (delta +3 lines, +4,194 chars; no PRD_FINALIZED.md existed, so PRD.md was the source).

Counts: 10 ambiguity-pins, 7 mismatch-revisions (17 edited passages total; several edits bundle both — classified by dominant nature below).

Changes (PRD section — insert|revise — ambiguity|mismatch — what changed — impl file:line):

- §2.2 — insert — ambiguity — pin ERR_NOT_FOUND for unmatched paths, ERR_METHOD_NOT_ALLOWED (405), ERR_INTERNAL (500) in the same envelope — app.py:34-46
- §2.3 — revise — ambiguity — pin limit/offset type-and-range validation (ERR_INVALID_REQUEST) and created_at tie-break by creation sequence — response.py:39-74, routes (e.g. railcars.py:101 sort key `(created_at, _seq)`)
- §2.4 — revise — ambiguity — pin initial `version` = 1 at creation — db.py:62-74
- §2.5 — revise — ambiguity — pin tonnage inputs rounded half-up to 3 decimals on intake, and `unit_rate_cents` rounded half-up to integer cents — util.py:44-46, domain.py:221-227
- §2.6 — revise — ambiguity — pin facility `name` at creation, PATCH bumps version, logical-singleton semantics (config read from first-created facility; defaults before any exists), and that `open_incident_count`-only changes do not bump `Facility.version` — facilities.py:16-74, domain.py:53-69, 90-94
- §2.9 item 11 — revise — ambiguity — add `ERR_CAR_NOT_SPOTTED` to the priority-11 constraint set — transfer_orders.py:113-114
- §3.1 — revise — ambiguity — pin `allocated_car_spots` integer ≥ 0; allocation-adjustment success returns HTTP 201 — customers.py:29, 97
- §3.1 — revise — mismatch — redefine `occupied_spots` as cars placed and not yet released (SPOTTED/IN_TRANSFER/EMPTY_AWAITING_CLEANING/CLEANING/READY_FOR_RELEASE; +1 at execution, −1 at release), and define the customer-level occupied/reserved usage with the same definitions across all tracks — domain.py:41-44, 286-300; spot_orders.py:227-228; railcars.py:255
- §3.1 — revise — ambiguity — pin equipment created with `name` + `equipment_type` — equipment.py:22-23
- §3.3 — revise — ambiguity — pin `quantity_remaining_tons` null until arrival — railcars.py:66
- §3.4 — revise — ambiguity — pin create-time checks: `spot_number` ≥ 1 and window ordering are shape errors (400); upper bound, capacity, overlap, posture, derail, credit not checked at creation — spot_orders.py:49-58
- §3.4 — revise — ambiguity — pin that a superseded `REQUESTED` order does NOT release its reservation (only superseded `SCHEDULED` does) — spot_orders.py:74-77
- §3.4 — revise — mismatch — schedule gate set re-ordered to impl's actual evaluation order (state → derail → suspended → car ARRIVED → track ACTIVE → spot range → window overlap → TRACK_FULL → switch-buffer → credit → allocation), and TRACK_FULL redefined as `occupied_spots + count(SCHEDULED spot orders on track) + 1 > spot_capacity` (REQUESTED orders excluded; the +1 counts this order), and the allocation check noted as already including this REQUESTED order in reserved — spot_orders.py:136-190, domain.py:303-308
- §3.4 — revise — mismatch — execution gate order: derail → suspended → car ARRIVED → track ACTIVE → window-active — spot_orders.py:211-222
- §3.5 — revise — mismatch — activation gates re-ordered to impl (suspended → elevated-hazmat → hold → contamination → car spotted → equipment available → car-busy/equipment-busy → credit); also pin create has no placement precondition and `risk_score` starts 0 until first activation — transfer_orders.py:49-56, 94-127
- §3.6 — revise — ambiguity — pin ticket creation has no parent-order-state precondition; certification checks ticket `DRAFT` before parent `ACTIVE`; voiding restores the three quantity ledgers only and never moves `placement_status` — weight_tickets.py:31-55, 92-97, 128-150
- §3.7 — revise — mismatch — release gate order: suspended → derail → hold → unpaid invoice; also pin start-cleaning on a non-`requires_full_clean` product is `ERR_INVALID_STATE` — railcars.py:186-189, 228-243
- §4 intro — revise — mismatch/ambiguity — pin the 201 exception for allocation-adjustments and enumerate every list endpoint's exact-match filter parameters — customers.py:97; list handlers in routes/*.py
- §5 catalogue — insert — ambiguity — add ERR_METHOD_NOT_ALLOWED (405) and ERR_INTERNAL (500) rows — app.py:39-46

The adjudicated lead (TRACK_FULL): confirmed mismatch — impl `spot_orders.py:171` weighs `occupied_spots + scheduled_count + 1` (SCHEDULED-only, excluding REQUESTED), whereas PRD §3.4 read as `occupied + reserved (REQUESTED+SCHEDULED), counting this order`. PRD revised to pin the impl formula, with a clarifying clause that pending REQUESTED orders do not fill the track. The reserved_spots counter semantics were verified against impl (create +1 always; cancel −1 for both REQUESTED and SCHEDULED; execute −1; supersede −1 only when the superseded order was SCHEDULED — the REQUESTED-supersede leak is intentional impl behavior and is now pinned).
