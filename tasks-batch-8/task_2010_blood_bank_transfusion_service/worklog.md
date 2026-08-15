# Worklog — task_2010_blood_bank_transfusion_service

Scenario: Blood Bank & Transfusion Service (hospital blood bank). User difficulty directive: "Generate task harder than expert level!"

## Step 2: Generate Scaffold — 2026-08-15T07:22:50.000Z

All three artifacts are complete and lint-clean. Final report:

### Output files
- `/home/ubuntu/github/CodingPRD/tasks/task_2010_blood_bank_transfusion_service/SCAFFOLD.yaml` (2,441 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_2010_blood_bank_transfusion_service/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2,483 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_2010_blood_bank_transfusion_service/SCAFFOLD_CORNER_DESIGN.yaml` (3,044 lines)

### §1.0–§1.7 scaffold counts
- **Entities: 15** — Patient, Supplier, SupplierOrder, BloodUnit (self-referential `derived_from_unit_id`), TypeAndScreen, TransfusionOrder, Crossmatch, MTPActivation, IssueRecord, TransfusionReaction, RecallCase, WastageRecord (append-only, `common_fields: false`), ParLevelPolicy, TransportCooler, CoolerCheckout
- **State machines: 13** (90 transitions), including a cyclic BloodUnit machine (AVAILABLE→RESERVED→ISSUED→AVAILABLE restock loop + QUARANTINED_HOLD with origin-state memory) and a branching/cyclic TransfusionOrder machine (verify fork, ON_HOLD↔reactivate loop, counter-derived targets)
- **Endpoints: 87** (incl. `/_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` default and `/_clock/sweep` test-driving maintenance)
- **Errors: 89** (all referenced; catalog verified orphan-free), **validations: 31** ordered rules, **calculations: 11**, **OCC concurrency rules: 2** (both true create/update races per §1.2.1's serial-observability filter)
- **Roles: 5**, all opaque, `segregation_of_duties` model (resulter≠validator, issuer≠verifier, reporter≠investigator, ack=ordering physician only)

### §1.8 difficulty design — 27 instances (min 18)
dual_variant_calc 2 (BloodUnit shelf-life fixed-vs-thawed; bucket posture physical-vs-prospective) · combinatorial_formula 3 covering **all three modes** — (a) ABO matrix with inverted plasma logic, (b) per-line-then-sum rounding with odd-cent prices so order is observable (123406 vs 123405 cents; emergency surcharge 154258), (c) MTP pack constitution with pinned evaluation order and preference-list-before-FEFO · non_linear_state_machine 3 · transitive_cascade 3 (depths 4/3/3, distinct triggers: sweep, execute-quarantine, suspend) · priority_pair_validation_conflict 3 (state×safety, safety×constraint, existence×state) · boundary_precision_check 4 (30m00s vs 30m01s, inclusive posture threshold, T&S expiry exact instant, empty-denominator wastage ratio) · cross_entity_state_dependency 4 · resource_temporal_overlap 2 (half-open zero-gap unit reservation vs closed+60-min-buffer cooler window) · compensating_invariant 3 (bucket unit conservation, reservation symmetry, wastage-ledger parity).

### §1.9 corner design — 85 instances across all 9 guide sections
62 active with full replayed recipes + 23 `excluded_because` stubs pointing at §1.8 instances. entities 10 · state_machines 18 · calculations 11 · validations 9 · endpoints 5 · errors 13 · rbac 9 (incl. 3 segregation-of-duties + ownership denials) · cross_cutting_layers 9 · consistency_model 1.

### Verification
Lint verdict block (verbatim, final run):
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(87 endpoints, 15 entities, 27 §1.8 + 62 §1.9 instances, 1,121 calls scanned.) Beyond lint the subagent ran a custom replay audit: placeholder closure (zero unbound `${var}`), OCC version freshness per chain, duplicate-specimen collision scan, and SoD identity inequality per chain — the only two SoD "violations" found are the intentional negative tests. Fixed en route: YAML flow-scalar `[` quoting in captures/grounds, a dead `ERR_COOLER_NOT_AVAILABLE` (cooler model redesigned so the interval rule — not status — gates booking), a dead `QC_FAILURE` wastage enum value, and prices changed to odd cents so the rounding-order rule is falsifiable.

Notable design choices: compliance/audit archetype with quota/allocation secondary; all temporal rules (72h T&S, 30-minute rule, 4h start window, 24h emergency-ack, expiry sweeps) are clock-driven and deterministic; cascades spelled hop-by-hop in transition `side_effects`; no random/id-based decisions anywhere (FEFO tie-break ends at `unit_number`, a client-supplied business key).

## Step 3: Copy Shared Files — 2026-08-15T07:23:10.000Z

Copied ./INSTRUCTION.md to tasks/task_2010_blood_bank_transfusion_service/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-15T07:40:00.000Z

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2010_blood_bank_transfusion_service/workspace/PRD.md` — 428 lines. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

### Section structure
- **§1 Introduction** — 2 paragraphs (safety/compliance framing + scope), `/blood-bank` mount stated.
- **§2 Global Specifications** — 11 subsections: 2.1 RBAC (5 roles, all `identity: opaque`, record-not-compare semantics, header errors); 2.2 response envelope (byte-identical to the canonical `section-2.2-response-structure.md`, verified by diff); 2.3 pagination (limit 10/1/100, offset 0, `created_at` ascending, 4 meta fields); 2.4 logical clock (startup default `2026-08-01T00:00:00Z`, `to_iso8601`/`current_utc`, sweep with its 5 output counters); 2.5 common properties (UUID id, 3-fractional-digit timestamps, `version`; WastageRecord append-only exception stated explicitly); 2.6 blood-component/demand-bucket/typing vocabulary; 2.7 precision (integer cents, half-up at pinned points, 4-decimal wastage rate, exact timestamps); 2.8 OCC; 2.9 validation pipeline (all 31 priorities in evaluation order, 15 resource-specific 404s, body-FK `ERR_NOT_FOUND` vs path-404 distinction); 2.10 posture ladders (physical vs prospective, inclusive boundaries, no-policy → `NORMAL`); 2.11 quarantine holds and cascades.
- **§3 Business Logic** — 9 subsections (3.1 patient/T&S, 3.2 suppliers/orders/intake, 3.3 orders/verification gates, 3.4 compatibility/crossmatch, 3.5 issue/30-minute rule, 3.6 MTP, 3.7 reactions/recall, 3.8 policies/wastage, 3.9 coolers). No HTTP methods or paths anywhere in §3.
- **§4 Endpoint table** — 87 rows, 4 columns (Method, Path, Description, Authorized Roles), 201/200 status rule paragraph.
- **§5 Error catalogue** — 89 rows, 2 columns.

### Scaffold → PRD translation map
- `entities` → §2.5/§2.6 + owning §3 subsections (all 141 field names in backticks with defaults, types, and source semantics).
- `state_machines` (13 machines, 89 distinct transitions) → §3.1–3.9 narratives; every from/to pair, precondition (paired with its error id), and side-effect cascade (T&S-expiry cascade, supplier-suspend hold, recall quarantine, reaction stop, return/stop order reverts, hold-wins release suppression, CONSUMED slot semantics, ISSUED sweep exemption).
- `calculations` (11) → unit expiration (§3.2, both variants with worked example), cost estimation (§3.2, pinned per-line-then-total rounding, tiers 20/50, 1.25 surcharge), physical/prospective posture (§2.10/§3.8), 7-step compatibility decision incl. full ABO matrices both directions (§3.4), FEFO selector (§3.4), `reserved_until` earliest-of with half-open boundary (§3.4), rolling wastage rate (§3.8), MTP pack waterfall with preference lists and shortfall semantics (§3.6), ABO confirmation latch (§3.1), return disposition with inclusive 30:00 boundary (§3.5).
- `validations` (31 priorities) → §2.9 ordered pipeline + trigger conditions scattered at each guarded workflow in §3 with exact error ids.
- `concurrency_rules` (2) → §2.8 (`expected_patient_version`, `expected_policy_version`, `ERR_STALE_VERSION`, 412, stale-view framing only).
- `endpoints` (87) → §4 table + §3 workflow narratives including side effects and response fields (`pack_number`, `issue_record_ids`, `shortfalls`, posture read fields, `as_of_utc`/`window_days`/`buckets`).
- `errors` (89) → §5 table + every id mentioned in §2/§3 prose.
- `roles` (5) → §2.1 with per-role opaque-identity prose; RBAC in §4 roles column.

### Coverage self-audit (all programmatic)
- **Contract 1 (Field-Name Coverage): PASS** — 141/141 entity fields, 74/74 endpoint input identifiers, 28/28 query params present in backticks; 0 missing (includes the dual naming of return payload keys `seal_intact`/`temperature_excursion` vs persisted `return_seal_intact`/`return_temperature_excursion`).
- **Contract 2 (Rule Coverage): PASS** — 89/89 error ids in §2/§3 prose; 50/50 state values; 106/106 enum values; 2/2 OCC rules with endpoint + occ field + error id + status; all 11 calculations with constants (1008/840/120/8760 h, 24/6/4 h derived clocks, 72 h windows, prices, tiers, 0.05 inclusive boundary, 30-day window, 0.0000 empty-denominator rule); all 13 state machines' transitions/preconditions/side effects expressed; validation priority order stated as a fixed pipeline; sibling branches symmetric (record-result, conclude, recall dispositions, reactivate targets, cancel from-states); 38/38 high-risk rule phrases verified (boundary inclusivity, hold-wins, not-revived, never-auto-clears, eligible-again-at-`reserved_until`, de-duplication, supervisor exemption, etc.).
- **Contract 3 (§3 Path Purity): PASS** — 953 backtick tokens scanned in §3; 0 path tokens, 0 bare HTTP methods, 0 method+path combos.
- **Contract precision:** §2.2 byte-identical to canonical source (diff-verified); no pseudocode operators (`==`, `>=`, `+=`, `min(`, `IN {`, `->`) outside the verbatim JSON blocks; no fuzzy/approximating words; pagination defaults/min/max and sort order explicit; both role-header names exact.

## Step 5: Generate Unit Tests — 2026-08-15T08:20:00.000Z

All 106 tests collect. The suite is complete. Final summary:

### File inventory

**`test_helpers/`** (Stage 1 — PRD-specific infrastructure):
- `types.py` — 25 status/vocabulary enums + 15 entity TypedDicts; `WastageRecord` correctly omits `updated_at`/`version` (append-only exception)
- `api_client.py` — `ApiClient(GenericApiClient)` with 91 methods covering all 87 PRD endpoints (incl. `_clock/set_current_utc`, `_clock/sweep`), all under `/blood-bank`
- `api_errors.py` — 76 `ApiErrorId` members + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity asserts + `assert_posture_read`, `assert_same_instant`/`assert_seconds_between` (parsed-instant comparison), three-fractional-digit format check
- `factories.py`, `constants.py` (shelf lives, windows, price/tier table, pack spec), `test_users.py` (all five roles are opaque per PRD §2.1 — named operators `tech-a/b/c`, `doc-1/2`, `sup-1`, `coord-1`, `qo-1/2`)
- `fixtures.py` — clock/sweep, intake (`make_stock`, `receive_order_units`, `release_unit`), typing chain with OCC threading, order/crossmatch/issue chains, composites: `setup_order_with_reserved_units`, `expire_patient_typing`, `setup_emergency_order_untyped`, `setup_started/transfused_issue`, `setup_investigating_reaction`, MTP/recall/cooler helpers
- `__init__.py` — barrel export

**`test_suite/`** (Stage 2): `conftest.py` + 15 test files (`test_01_`…`test_15_`), pytest-collectable (106 collected).

### Test counts

- **Queue A (Difficulty): 44 tests over 22 generated instances (≥2 each); 5 instances skipped**
- **Queue B (Corner): 62 tests over all 62 non-stub instances (1 each); 23 `excluded_because:` stubs correctly untranslated** (all stub cross-references resolve to real difficulty instance names)
- **Total: 106 tests**

### Per-instance disposition

**Queue A — generated (22):** `ffp_unit_fixed_shelf_vs_thawed_clock`, `bucket_physical_vs_prospective_posture`, `compatibility_decision_abo_plasma_inversion`, `supplier_order_cost_per_line_then_total_rounding`, `mtp_pack_constitution_evaluation_order`, `blood_unit_issue_return_restock_cycle`, `transfusion_order_hold_reactivate_loop`, `reaction_investigation_fork_divergent_side_effects`, `recall_quarantine_cascade`, `ts_expiry_sweep_cascade`, `supplier_suspension_cascade`, `state_vs_safety_on_held_order_issue`, `safety_vs_constraint_on_fulfilled_order_crossmatch`, `return_thirty_minute_boundary`, `posture_critical_threshold_inclusive`, `wastage_rate_empty_denominator`, `reaction_close_requires_recall_notifications`, `order_reactivate_requires_fresh_type_and_screen`, `cooler_checkout_buffer_gap_semantics`, `bucket_unit_count_conservation`, `order_reservation_symmetry`, `wastage_ledger_parity`.

**Queue A — skipped (5), PRD-first gaps:**
| Instance | Skip reason |
|---|---|
| `priority_pair_validation_conflict/existence_vs_state_on_issue` | Pins `ERR_UNIT_NOT_FOUND` for a body-FK miss; PRD §2.9 stage five derives "the generic `ERR_NOT_FOUND` (HTTP 404)" — asserted outcome contradicts the PRD |
| `boundary_precision_check/ts_expiry_exact_instant_crossmatch_rejected` | Asserts crossmatch **create** fails `ERR_TS_NOT_ACTIVE` at the expiry instant; PRD §3.4 gates T&S only at record-result, never at create |
| `cross_entity_state_dependency/crossmatch_requires_active_type_and_screen` | Same create-time T&S gate absent from PRD §3.4 |
| `cross_entity_state_dependency/issue_requires_reserved_unit_for_this_order` | PRD §3.5 states the RESERVED-for-this-order requirement but names no error_id for its violation |
| `resource_temporal_overlap/unit_reservation_half_open_adjacency` | Asserts create-time rejection of a RESERVED unit; PRD checks unit availability only at record-result |

Ripple: corner stubs `existence_vs_state_priority_corner`, `ts_active_at_exact_expiry_corner`, `error_ts_not_active_corner` cite skipped difficulty instances, so those claims remain uncovered gaps (per the stub rule, no corner tests were emitted).

**Queue B — all 62 non-stub instances generated; 23 stubs not translated.**

**Sanctioned relaxations** (per the final-pass "remove or relax" rule — sub-assertions the PRD does not uniquely derive were dropped, never weakened to generic checks): absolute `version` literals → relative +1-per-mutation or presence/type (PRD pins the increment, not the initial value); timestamp string equality → parsed-instant equality (PRD pins "exact to the second", not the rendering); wastage-summary bucket *entry* field names dropped (PRD names only top-level keys) while the excessive flag, sweep counters, window echo, and pinned literals were asserted; receipt atomicity count dropped from `over_receipt_returns_422`.

### Self-audit verdict

- **Stage 1:** all modules compile/import; client mirrors §1.5 exactly; `common_fields: false` honored; fixture identity threading uses named opaque operators (segregation pairs always distinct).
- **Stage 2:** 106/106 tests collect; every test carries exactly one terminal `Design:` tag resolving to a real instance (0 dangling, 0 dual, 0 stubs translated); 164/164 docstring quotes verbatim-match PRD.md (whitespace-normalized grep); 0 `skip`/`skipif`/`xfail`; 0 "scaffold" mentions in helpers or tests. The only coverage shortfalls are the 5 documented PRD-first skips above — gaps left as gaps.

## Step 6: Generate Implementation — 2026-08-15T08:45:00.000Z

The implementation is complete and verified. Here is the summary.

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_2010_blood_bank_transfusion_service/workspace/implementation/`

### File inventory
- `start.sh` (executable) — guarded launcher: `pip install -q -r requirements.txt` only when `import flask` fails (no-op on per-test reboots), then `exec python3 app.py`
- `requirements.txt` — `flask>=3.0,<4` (3.1.3 present in environment)
- `app.py` — Flask app, blueprint registration, `ApiError`/404/405/500 handlers, `app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)`
- `store.py` — in-memory `DB` (14 entity tables) + logical clock defaulting to exactly `2026-08-01T00:00:00Z`; `new_entity`/`new_event`/`touch` helpers (`WastageRecord` carries only `id`+`created_at`, per PRD §2.5)
- `constants.py` — enum sets, shelf-life/price tables, window constants, ABO matrices, pack spec
- `errors.py` — `ApiError` + all 60+ catalog error IDs verbatim
- `envelope.py` — exact PRD §2.2 envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; list responses add `limit`/`offset`/`total_count`/`has_more`), pagination with clamping
- `common.py` — auth decorator (headers `X-User-ID`/`X-User-Role`, stage 1/2), schema validators (stage 4), resource-specific path 404s (stage 3), generic `ERR_NOT_FOUND` body-FK lookups (stage 5)
- `logic.py` — calculations: unit expiry (fixed + thaw/pool clocks), physical/prospective posture ladders (inclusive `<=`), rolling wastage rate (round-half-up 4dp, `Decimal`), estimated cost (pinned line-then-total half-up rounding), 7-step compatibility decision, FEFO selector (expires_at → created_at → unit_number), MTP waterfall pack constitution, order counter reconciliation, hold/cancel/expire machinery, the sweep
- `serializers.py` — per-entity serializers with dynamic computed fields (`has_active_type_and_screen`, `active_mtp`, `ack_overdue`, `overdue`, policy posture fields)
- `routes_admin.py` (clock, patients, suppliers, policies, coolers/checkouts, wastage views), `routes_supply.py` (supplier orders + receive, blood-unit intake), `routes_clinical.py` (T&S, orders, crossmatches, issues, MTP), `routes_quality.py` (reactions, recalls)

### Endpoint count
87 PRD endpoints registered (88 routes minus Flask's built-in `/static`).

### State storage
Purely in-memory module-level dictionaries in `store.py`, keyed by UUID `id`. **No seeding at startup** — verified: all 14 list endpoints report `total_count: 0` on a fresh boot. Every write goes through `touch()` (refreshes `updated_at`, increments `version`).

### start.sh
Reads `PORT` (default 10000), binds `0.0.0.0`, runs in the foreground via `exec python3 app.py`; dependency install guarded by `python3 -c "import flask"`. Verified: three independent fresh `bash start.sh` boots each passed a full suite (main workflow 80 checks, boundary checks 46, state-machine/RBAC checks 47 — all green).

### PRD-ambiguity adjudications
1. **Consumed-crossmatch slot loss on return** — PRD §3.5 says a return "decrements units_issued_net" while the BloodUnit ISSUED→AVAILABLE note says "fulfillment is recomputed and may drop READY→AWAITING_CROSSMATCH". Under literal never-decrement accounting that drop is unreachable and orders deadlock after a restock, so on return/stop of an issue that consumed a crossmatch I decrement `units_crossmatched` too (the CONSUMED crossmatch is still not revived). At consume time `units_crossmatched` is not decremented (per the explicit CONSUMED side effect).
2. **Duplicate `mrn` / `license_number` / `cooler_tag`** — the PRD declares them unique but the catalog has no dedicated error; I reject with `ERR_INVALID_REQUEST` (400).
3. **Pagination out of range** (`limit=0/500`, non-numeric) — clamped to [1,100]/[0,∞] with defaults, matching the established repo convention (sibling task implementations), not rejected.
4. **`recall-cases?unit_id=` filter** — matches cases whose scope `unit_id` equals the value OR whose pinned `implicated_unit_ids` contain it.
5. **`acknowledge-emergency` on MTP-dispatched issues** (which have `order_id: null`) — the physician-identity check compares against the activation's `activated_by_physician_id` instead of an order's `ordering_physician_id`.
6. **Cooler return after sweep-released occupancy** — the state machine defines only `CHECKED_OUT→RESTOCKING` on return, so returning an overdue checkout whose cooler was already released to `AVAILABLE` leaves the cooler `AVAILABLE` (no retroactive restock buffer).
7. **`wastage-summary` bucket entry shape** (unspecified in PRD/scaffold) — entries are `{product_type, abo_type, rh_type, wasted_units, received_units, wastage_rate, excessive_wastage}` for every bucket present in units or wastage records, sorted by bucket key; invalid `window_days` falls back to 30.
8. **Unknown role string** (present but not one of the five) → `ERR_UNAUTHORIZED_ROLE` (403); the 400 header error covers only missing/empty headers per PRD §2.1.
9. **`thawed_at` on non-FFP/CRYO units** — scaffold formula's literal `else 0h` branch is applied (derived expiry = `thawed_at`), per the pinned formula.
10. **Antibody→antigen mapping** — `anti-K` matches a unit whose `antigen_negative` contains `K` (strip the `anti-` prefix; bare names used as-is).
11. **Emergency Rh relaxation and WHOLE_BLOOD** — step 5 says "red-cell-class products", so POS→NEG is relaxed for WHOLE_BLOOD too under EMERGENCY urgency, with ABO identity still enforced.
12. **Negative policy thresholds** → `ERR_THRESHOLD_ORDER_INVALID` (PRD §3.8 bundles "each at least zero" into that error); negative `min_shelf_life_hours` → `ERR_INVALID_REQUEST`.
13. **Order completion from any active-band state** — the machine lists only PARTIALLY_ISSUED→COMPLETED, but an emergency-issued AWAITING_CROSSMATCH order reaching `units_transfused == units_requested` would otherwise be uncompletable, so completion is allowed from AWAITING_CROSSMATCH/READY/PARTIALLY_ISSUED.
14. **Patient.version bumps** only where the scaffold explicitly lists them (T&S create, T&S validate, sweep loss of last active T&S, complete-transfusion, MTP activate/deactivate); stand-down flips `active_mtp` (computed live) without a version bump.
15. **`meta.api_request_timestamp`** uses the logical clock (PRD §2.4: all temporal reasoning uses it), giving deterministic envelopes.
16. **Issue pipeline ordering** — unit state/linkage (`ERR_UNIT_NOT_AVAILABLE`) is evaluated in the state group (priority 7) before business rules; `ERR_ORDER_ISSUE_QUOTA_MET` (priority 23) remains reachable via plasma/emergency auto-select issues, and explicit-unit compatibility (422, priority 8) precedes the crossmatch fulfillment ceiling (priority 22) per §2.9.
17. **UNIT-scope recall identification** includes the named unit plus the transitive `derived_from_unit_id` descendant closure, of any status; sort by `created_at` ASC then `unit_number` ASC.
18. **`received_summary`** is initialized at order creation with one entry per line (`received_qty: 0`), so partial receipts and auto-close bookkeeping are observable from creation onward.
19. **Wastage `recorded_by_user_id`** is the literal string `system` for sweep-created (`EXPIRED`) and closure-created (`RECALL_DESTRUCTION`) records; `REACTION_INVESTIGATION` records carry the concluding officer's id; manual discards/returns/stops carry the caller's id.

## Step 7: Run Tests and Iterate — 2026-08-15T09:05:00.000Z

**Summary**

- **Iterations run:** 2 full 8-round parallel sweeps. Sweep 1 surfaced 3 deterministic failures (identical across all 8 rounds — no flakiness). Sweep 2 after fixes: all 8 rounds 106/106 passed, 0 failed, 0 errors, independently re-verified from `results.1..8.json`.

- **Tests deleted:** none.

- **Fixes applied to `test_suite/`** (3 tests, 2 files):
  1. `test_suite/test_02_supplier_intake_and_inventory.py` — `test_error_duplicate_unit_number`: added `set_clock()` at test start. The duplicate-manifest request used `collected_at="2026-08-02"` while the logical clock sat at the default `2026-08-01`, so §2.9's pipeline correctly answered the earlier-priority `ERR_SPECIMEN_TIME_INVALID` before unit-number uniqueness. Setup inconsistent with PRD; implementation verified faithful.
  2. `test_suite/test_12_mtp.py` — `test_mtp_pack_composition_and_preference_over_fefo`: STEP 1b unique-derivability collapse. §3.6's platelet preference "or O when untyped" and §3.4 step 2's untyped plasma-class AB-only short-circuit (platelets are plasma-class per §2.6, and §3.6 fills "per the FEFO selector" whose pool passes "the full compatibility decision") admit two faithful readings; the PRD produced both the test's reading and the implementation's. Split per STEP 1c: removed reading-dependent assertions (issue count == 5, exact `shortfalls` array, U-P-O ISSUED); kept/strengthened assertions holding under both readings (U-R1/U-R2/U-F1/U-F2 ISSUED, `{RBC, missing_qty: 2}` shortfall membership, U-P-A AVAILABLE, pack_number == 1).
  3. Same file — `test_mtp_pack_issues_emergency_semantics`: replaced hard-coded `units_issued_total == 5` (depends on the same ambiguous platelet interaction) with the PRD-verbatim invariant `units_issued_total == len(pack["issue_record_ids"])` ("tracks every issue record created under it"); per-issue emergency-field assertions kept unchanged.

- **Fixes applied to `test_helpers/`:** none — triage confirmed no shared fixture fault; each failure traced to its own test function.

- **Fixes applied to `implementation/`:** none — in all three cases the implementation was the PRD-faithful party (pipeline priority order per §2.9; FEFO selector with compatibility filter per §3.4/§3.6). Both MTP test edits were empirically validated against a live server replay before the verification sweep.

- **Feedback notes for generators:** the MTP platelet case is a unique-derivability miss worth flagging to doc-generator — §3.6's "or O when untyped" platelet preference is rendered inert by §3.4 step 2's plasma-class AB-only short-circuit for untyped patients (Zero-Silence Rule: the PRD never states whether the compatibility filter applies inside the MTP preference walk), and unit-test-generator should not assert a concrete resolution of that interaction.

## Step 8: Finalize PRD — 2026-08-15T09:12:00.000Z

The diff confirms exactly two inline insertions, both within §3.6's dispatch paragraph; nothing else changed. Final summary:

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2010_blood_bank_transfusion_service/workspace/PRD_FINALIZED.md`

**Line counts / delta:** PRD.md 427 lines / 81,453 bytes → PRD_FINALIZED.md 427 lines / 82,184 bytes. Line-count delta 0% (both edits are inline insertions into an existing paragraph line); size delta +731 bytes (+0.90%).

**Step 7 item disposition:**
- Item 1 (`test_error_duplicate_unit_number` `set_clock()` fix) — pure test-setup bug. PRD §2.4 already pins the clock default (`2026-08-01T00:00:00Z`) and §2.9 already pins `ERR_SPECIMEN_TIME_INVALID` ahead of `ERR_DUPLICATE_UNIT_NUMBER` in the pipeline. **No PRD edit.**
- Items 2–3 (`test_12_mtp.py` relaxations) — same root cause: §3.6 never stated whether the §3.4 compatibility filter applies inside the MTP preference walk. Implementation applies it (per-bucket `fefo_select` → `fefo_candidates` → `unit_compatible` filter). **Two edits, both in §3.6.**

**Changes (one bullet each):**
- §3.6 — insert — after "…then moving on.": new sentence pinning that the per-bucket MTP fill runs the §3.4 FEFO selector with its compatibility-decision eligibility filter intact inside the preference walk, evaluated for the dispatch with no order type-restriction and with the standing emergency Rh-mismatch allowance in force; incompatible buckets yield no candidates and the walk moves on — `implementation/logic.py:663-695` (`dispatch_mtp_pack`, ctx at 669-673, per-bucket `fefo_select` at 682-687), filter at `logic.py:336`.
- §3.6 — insert — after the apheresis-platelet preference sentence: pins that the compatibility filter still governs inside the platelet walk, so for an untyped patient §3.4's plasma-class short-circuit admits only group-`AB` units — the O-, A-, B-negative buckets are walked but fill nothing, and the platelet component fills from AB-negative stock alone or else shortfalls — `implementation/logic.py:647-652` (`mtp_preference_buckets` platelet branch), `logic.py:253-259` (untyped plasma-class AB short-circuit in `unit_compatible`).

**Per-edit pre-edit search log:**

*Edit 1 (selector-filter-inside-walk sentence):*
- (a) Subject: whether the full compatibility decision filters candidates inside the §3.6 MTP per-bucket preference walk, and under what dispatch context.
- (b) Enumerated impl paths: `logic.py:319-340` (`fefo_candidates` — filter applied for every caller), `logic.py:343-345` (`fefo_select`), `logic.py:243-311` (`unit_compatible` — all seven steps; only step 5 reads `urgency`), `logic.py:621-660` (`mtp_preference_buckets` — FFP typed pre-filter at 645-646, platelet branch unfiltered), `logic.py:663-695` (`dispatch_mtp_pack` — ctx: `urgency="EMERGENCY"`, `type_restriction="NONE"`, patient `special_requirements`), `routes_clinical.py:351-399` (`xm_create` explicit+auto), `routes_clinical.py:502-557` (`issue_create` explicit+auto, standard and emergency), `routes_clinical.py:419-451` (`xm_record_result` — verified it does NOT re-run compatibility), `routes_clinical.py:783-819` (`mtp_dispatch` route). Grep confirmed no other consumers of `fefo_select`/`unit_compatible`/`mtp_preference_buckets`.
- (c) Wording adjustments: scoped the claim to "inside the preference walk … evaluated for the dispatch" so the no-type-restriction clause cannot mis-describe the order-based paths (xm/issue create carry the order's `type_restriction`); said "with its eligibility filter intact" rather than "unchanged" to avoid asserting anything about ranking/expiry mechanics beyond the filter; included the emergency-Rh clause because §3.4 step 5 keys the relaxation on order urgency and MTP has no order — matching what §3.6's RBC sentence already implies and impl ctx `urgency="EMERGENCY"`.

*Edit 2 (untyped platelet consequence sentence):*
- (a) Subject: the concrete outcome of the platelet preference walk for an untyped patient.
- (b) Enumerated impl paths: `logic.py:647-652` (untyped → `first_abo="O"`; list `[(O,NEG),(A,NEG),(B,NEG),(AB,NEG),(O,NEG)]` deduped at 653-660 to four buckets), `logic.py:253-259` (untyped plasma-class → AB only, Rh ignored), `logic.py:678-694` (empty buckets → shortfall with `missing_qty`), plus the §3.3 gating text at PRD line 159 (`UNKNOWN`→`AB:NEG` bucket mapping) verified to be a different subject (demand-bucket gating, not unit selection) and untouched.
- (c) Wording adjustments: said "are walked but can fill nothing" (not "the preference collapses") to preserve the impl's actual walk order — the (O,NEG) bucket is genuinely visited first; scoped the clause to untyped patients only so typed-patient platelet walks are not narrowed; "fills from AB-negative stock alone or else shortfalls" matches the impl exactly.

**Verification of behavioral equivalence:** under the finalized wording, the test_12 fixture (untyped patient; 2×RBC O-NEG, 2×FFP AB-NEG, 1×PLT O-NEG, 1×PLT A-NEG) deterministically yields: U-R1/U-R2/U-F1/U-F2 ISSUED, shortfalls `{RBC:2}` and `{PLT_APHERESIS:1}`, U-P-O and U-P-A remain AVAILABLE, `units_issued_total == 4 == len(issue_record_ids)` — exactly the implementation's behavior.

## Step 9: Complete PRD — 2026-08-15T09:25:00.000Z

All edits are in place: 30 lines changed, all inline (the file's paragraph-per-line structure means each change is one line), no new sections. Here is the final summary.

**Source vs. output:** `PRD_FINALIZED.md` 427 lines / 82,184 chars → `PRD_COMPLETED.md` 427 lines / 87,033 chars (**+4,849 chars, +0 lines**). All changes are in-paragraph inserts/revisions.

**Counts:** 29 ambiguity-pins, 8 mismatch-revisions (37 change bullets across 30 edited paragraphs).

### Ambiguity-pins (insert)

- §2.3 — insert — ambiguity — limit/offset out-of-range or unparseable values are clamped/defaulted, not rejected; list sort ties break by insertion order — envelope.py:47-82
- §2.4 — insert — ambiguity — sweep counter membership pinned: `crossmatches_expired_count` includes cascade- and unit-expiry-driven expiries, `orders_held_count` counts T&S-cascade holds, `coolers_restocked_count` counts only RESTOCKING→AVAILABLE — logic.py:526-614
- §2.5 — insert — ambiguity — `version` starts at one on creation — store.py:51-62
- §2.10 — insert — ambiguity — inbound horizon includes `expected_delivery_at` at or before now+24h, including already-past ETAs on undelivered orders — logic.py:104-125
- §3.1 — insert — ambiguity — duplicate `mrn` rejected with `ERR_INVALID_REQUEST` — routes_admin.py:68-69
- §3.1 — insert — ambiguity — `has_active_type_and_screen` list filter parses `true`/`false` case-insensitively against the live-computed flag; other values yield an empty page — routes_admin.py:96-103
- §3.1 — insert — ambiguity — `antibody_identifications` supplied with a NEGATIVE screen are accepted and stored verbatim — routes_clinical.py:111-122
- §3.2 — insert — ambiguity — duplicate `license_number` rejected with `ERR_INVALID_REQUEST` — routes_admin.py:124-125
- §3.2 — insert — ambiguity — `lines` must be non-empty; duplicate product/ABO/Rh triples permitted across lines — routes_supply.py:30-47
- §3.2 — insert — ambiguity — `received_summary` (per-line zeros), `total_units_received` 0, `backordered` false initialized at creation — routes_supply.py:66-77
- §3.2 — insert — ambiguity — receipt batch is atomic (whole batch validated before any unit created); `units` payload must be non-empty — routes_supply.py:163-165, 181-216
- §3.2 — insert — ambiguity — `expires_before` filter is a strict less-than; unparseable value draws `ERR_INVALID_REQUEST` — routes_supply.py:312-317
- §3.3 — insert — ambiguity — order opens with `requires_crossmatch` already fixed, `type_restriction` NONE, `demand_bucket` null, snapshot empty — routes_clinical.py:200-219
- §3.3 — insert — ambiguity — return/stop (incl. reaction-driven) also decrements `units_crossmatched` when the removed issue had consumed a crossmatch — logic.py:380-393, routes_clinical.py:61-69 (routes_quality.py:61-69)
- §3.3 — insert — ambiguity — counter recompute moves only READY (crossmatch loss) or PARTIALLY_ISSUED (issue loss); ON_HOLD and other states keep state while counters move — logic.py:363-393
- §3.3 — insert — ambiguity — order cancel requires only the OrderingPhysician role; caller identity is not compared to `ordering_physician_id` — routes_clinical.py:308-324
- §3.4 — insert — ambiguity — crossmatch creation carries no order-state precondition beyond the fulfillment ceiling — routes_clinical.py:362-399
- §3.4 — insert — ambiguity — record-result stamps `resulted_at`/`resulted_by_user_id` at attempt start; they persist on a failed COMPATIBLE branch without `updated_at`/`version` change — routes_clinical.py:425-440
- §3.5 — insert — ambiguity — missing `unit_id` on a standard red-cell issue draws `ERR_INVALID_REQUEST` (400); explicit-unit state/linkage rule (RESERVED-for-this-order consumed, else must be AVAILABLE; anything else `ERR_UNIT_NOT_AVAILABLE` 409) evaluated before the compatibility re-run — routes_clinical.py:488-520
- §3.5 — insert — ambiguity — an emergency release against an AWAITING_CROSSMATCH order increments `units_issued_net` but leaves the order in AWAITING_CROSSMATCH — logic.py:373-377
- §3.5 — insert — ambiguity — return paragraph pins the `units_crossmatched` decrement when the returned issue consumed a crossmatch — routes_clinical.py:646-688
- §3.5 — insert — ambiguity — MTP-dispatched issues are acknowledged by the activation's `activated_by_physician_id`; the 24h boundary is inclusive (exactly at the mark still succeeds) — routes_clinical.py:709-729
- §3.6 — insert — ambiguity — `activation_reason` under ten characters draws `ERR_INVALID_REQUEST` (400) — routes_clinical.py:741-743
- §3.7 — insert — ambiguity — scope-field exclusivity: off-scope fields present (e.g. DONOR with `lot_number`, non-DONOR with `implicated_since`) rejected as `ERR_RECALL_SCOPE_INVALID` — routes_quality.py:260-271
- §3.7 — insert — ambiguity — recall list `unit_id` filter matches scoping `unit_id` or membership in `implicated_unit_ids` — routes_quality.py:302-307
- §3.8 — insert — ambiguity — `min_shelf_life_hours` must be an integer ≥ 0 — routes_admin.py:220, 278
- §3.8 — insert — ambiguity — wastage summary: bucket set = triples referenced by any unit or wastage record, sorted lexicographically; entry fields `product_type/abo_type/rh_type/wasted_units/received_units/wastage_rate/excessive_wastage`; invalid `window_days` silently falls back to 30 — routes_admin.py:458-496
- §3.9 — insert — ambiguity — duplicate `cooler_tag` rejected with `ERR_INVALID_REQUEST` — routes_admin.py:325-326
- §3.9 — insert — ambiguity — returning a checkout whose cooler is no longer CHECKED_OUT (sweep already released it) leaves the cooler as-is; no restock buffer begins — routes_admin.py:414-429

### Mismatch-revisions (revise)

- §2.9 — revise — mismatch — an unmatched route yields the generic `ERR_NOT_FOUND`, not a resource-specific 404 (unknown path ids remain resource-specific) — app.py:34-41
- §3.1 — revise — mismatch — `identified_antibodies` is also retained after specimen expiry (PRD listed only the three typing fields) — logic.py:495-519
- §3.2 — revise — mismatch — over-receipt cap applies to the summed ordered quantity per product/ABO/Rh triple (not per line), with batches filling earlier matching lines first — routes_supply.py:182-204
- §3.3 — revise — mismatch — `requires_crossmatch` is fixed at creation by the product-class rule; verify fills only `type_restriction` and `demand_bucket` — routes_clinical.py:207, 281-289
- §3.3 — revise — mismatch — `units_transfused` reaching `units_requested` completes an order from AWAITING_CROSSMATCH, READY, or PARTIALLY_ISSUED (not only PARTIALLY_ISSUED); other states unmoved — logic.py:396-405
- §3.3 — revise — mismatch — reactivation's third branch has no `units_transfused` qualifier: fulfillment satisfied with `units_issued_net` ≥ 1 lands in PARTIALLY_ISSUED regardless — routes_clinical.py:336-342
- §3.4 — revise — mismatch — FEFO shelf-life horizon: unscoped selection (crossmatch/issue auto-select) always uses the 4-hour default; only bucket-scoped walks (MTP dispatch) apply the bucket policy's `min_shelf_life_hours` — logic.py:319-345 with constants.py:69
- §3.6 — revise — mismatch — `active_mtp` is read live (true exactly while an activation stands ACTIVATED): it reads false from stand-down on, stand-down does not touch the patient record, and deactivation merely advances the patient's `version` — routes_clinical.py:830-865, serializers.py:33

**Notable confirmed-equivalent areas (no change needed):** the full ABO/Rh compatibility matrices (constants.py:78-90 + logic.py:243-311 exactly reproduce PRD's per-type enumeration including the emergency Rh relaxation for both RBC and WHOLE_BLOOD), cost-estimation rounding pipeline, unit-expiration dual clocks, MTP pack preference walks, all state-machine from-state guards and error codes, the §2.9 pipeline ordering (impl comments cross-check against it at every stage), and all boundary inclusivity rules (30-minute rule, 4-hour start window, 72-hour validity, reservation half-open window).
