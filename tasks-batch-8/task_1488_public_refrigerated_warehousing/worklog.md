# Worklog — task_1488_public_refrigerated_warehousing

## Step 1: Create Task Directory — 2026-08-13T12:36:00.000Z

Pre-assigned directory `tasks/task_1488_public_refrigerated_warehousing/` (with `workspace/`) verified present and empty. Step 1 treated as DONE per command args.

## Step 2: Generate Scaffold — 2026-08-13T13:59:00.000Z

All three artifacts are generated, validated, and lint-clean. Final summary:

## Generated artifacts

All under `/home/ubuntu/github/CodingPRD/tasks/task_1488_public_refrigerated_warehousing/`:

- **SCAFFOLD.yaml** (1586 lines) — §1.0–§1.7 only, no design keys
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** (1023 lines) — single `scaffold_difficulty_design:` key
- **SCAFFOLD_CORNER_DESIGN.yaml** (916 lines) — single `scaffold_corner_design:` key

## Scaffold contents (§1.1–§1.7)

- **Profile**: quota_allocation × ledger_reconciliation; layers = optimistic_concurrency, cascading_side_effects, rate_threshold_triggers, ops_run_checkpoint; flat topology; segregation_of_duties role model; immediate consistency. Logical clock endpoint with pinned startup default `2026-08-01T00:00:00Z`.
- **Entities: 14** — Customer, RateCard, TemperatureZone, InboundReceipt, InventoryLot, Pallet, OutboundOrder, Allocation, BlastFreezeCell, BlastFreezeBooking, TemperatureExcursion, RecallEvent, Claim, Invoice
- **State machines: 12** — incl. Pallet as parallel dimensions (custody status × quality), cyclic OutboundOrder (SUBMITTED→SHORTED→DRAFT→ALLOCATED, plus cascade demotion), cyclic Claim (DENIED→REOPENED→UNDER_REVIEW appeal loop), cyclic Invoice dispute loop, compound InventoryLot (status derived from child pallets)
- **Calculations: 10** — incl. dual-variant storage_charge (DAILY_PRORATED vs FULL_MONTH), dual-variant claim_settlement (DECLARED_VALUE vs LIMITED_LIABILITY), forward-looking handling_out with pinned tier→fee→credit evaluation order, per-pallet-round-then-sum storage, tiered dwell surcharge with blast-freeze clock reset, FIFO selector (production_date → received_at → created_at, never id)
- **Validations: 11** priority tiers (auth → schema → role → ownership → existence → state → safety → temporal → constraint → referential → fiscal)
- **Endpoints: 68** (all FKs reverse-reachable via filtered lists; lists sorted created_at ASC for deterministic index captures)
- **Errors: 24** — every code referenced by at least one validation/transition and exercised by a recipe
- **Roles: 5** — CustomerAdmin (entity_backed:Customer), WarehouseOperator / QualityManager / ClaimsAdjuster / BillingAdmin (opaque); SoD: excursion reporter barred from confirming it

## §1.8 difficulty design: 27 instances (3 per rule × 9 rules)

dual_variant_calc 3 · combinatorial_formula 3 (modes a/b/c: dwell multi-input, round-then-sum, credit-check evaluation order) · non_linear_state_machine 3 (Pallet/Order/Claim) · transitive_cascade 3 (excursion depth-4, recall depth-3, manual-release depth-2) · priority_pair_validation_conflict 3 (safety>fiscal, state>constraint, authz>state) · boundary_precision_check 3 (exact capacity fill, dwell==60 days, settle exact cents) · cross_entity_state_dependency 3 (Order↔Pallet, Receipt↔Zone, Claim↔Excursion) · resource_temporal_overlap 3 (cell buffer vs dock aggregate-capacity vs cancelled-booking candidate set) · compensating_invariant 3 (pallet counts, invoice money, cell calendar time)

All numeric asserts are precomputed literals (e.g. storage 2700 vs 3000; rounding 99≠100; dwell 750; claim 8000 vs 50000; credit 100000==limit passes / 100450 fails; settle 8199 rejects / 8200 settles).

## §1.9 corner design: 49 instances (37 active + 12 excluded_because stubs)

entities 6 · state_machines 5 · calculations 4 · validations 13 · endpoints 2 · errors 8 · rbac 4 · complexity_layers 6 · consistency_model 1

## Verification

- `scaffold_lint.py`: **VERDICT: clean lint** — 665 calls scanned across §1.8+§1.9, all conform to §1.5; all FKs reverse-reachable (verbatim verdict block above)
- Separate replay script: 76 unique instance names across both files, zero unbound `${var}` placeholders, all `grounds:` resolve to declared §1.1–§1.7 elements, all stubs cite real §1.8 instances, no catalog-only errors
- Forbidden-vocabulary scan (simultaneously / first-writer-wins / in parallel / race winner…): clean
- Two authoring bugs caught and fixed during self-review: a dead `ERR_LOT_RECALLED` precondition on release-quarantine (recalled pallets leave QUARANTINED quality, so it could never fire — removed from spec), and a misleading posture label in one assert (TIGHT vs OPEN after a slot frees)

## Step 3: Copy Shared Files — 2026-08-13T14:02:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1488_public_refrigerated_warehousing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T14:10:00.000Z

All three hard contracts PASS. The PRD is complete and verified.

## Summary

**Generated:** `/home/ubuntu/github/CodingPRD/tasks/task_1488_public_refrigerated_warehousing/workspace/PRD.md` — 330 lines, from `SCAFFOLD.yaml` (the difficulty/corner design files were never opened).

**Section structure:**
- §1 Introduction — 2 paragraphs (business context + the two governing commitments: pallet-granularity bailment accountability, provisional accrual vs finalized billing)
- §2 Global Specifications — 10 subsections: 2.1 RBAC (5 roles with identity semantics: `CustomerAdmin` entity-backed vs 4 opaque roles), 2.2 Response Structure (byte-verbatim from `section-2.2-response-structure.md`, confirmed by containment check), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), then domain-derived subsections: 2.4 The Logical Clock (2026-08-01T00:00:00Z startup default), 2.5 Common Resource Properties, 2.6 Monetary Representation and Rounding (integer cents, round-half-up, per-pallet-then-sum pinning, negative totals allowed), 2.7 OCC (both rules with `expected_customer_version`/`expected_order_version` → `ERR_STALE_VERSION` 412), 2.8 Zone Capacity Accounting and Storage Posture, 2.9 Request Validation Order (all 11 scaffold priority tiers as an explicit earliest-tier-wins cascade), 2.10 Bailment and the Open-Invoice Accrual Model
- §3 Business Logic — 9 subsections organized by business process: onboarding/rate cards, inbound receiving, dual-dimension pallet/lot custody, blast freezing, outbound FIFO release, excursion quarantine cascade, recalls/disposition, claims, monthly billing. All 10 calculations translated to precise prose (no operator syntax, constants embedded: "ten percent rounded down", "divided by thirty", dwell tiers 60/90/120 days, volume tiers 100/500), all state transitions with from→to states, all side-effect cascades (4-hop quarantine, recall activation, ship, completion), all validation conditions paired with their error IDs near the workflows they guard
- §4 Endpoint table — 68 rows (verified exact match to scaffold methods+paths), 4 columns only
- §5 Error catalogue — 24 rows, 2 columns, codes verified against scaffold (incl. 412 and 422 outliers)

**Hard contract audit results:**
- Contract 1 (Field-Name Coverage): PASS — 68/68 entity fields, 49/49 request-body inputs, 14/14 query params, 1/1 path params, plus outputs (`current_utc`, `finalized_count`, `finalized_invoice_ids`), all backticked
- Contract 2 (Rule Coverage): PASS — priorities cascade, both OCC rules, all transitions/calculations/validations/side-effects expressed; 16 spot anchors verified (reservation-released-before-capacity ordering, submit evaluation order, credit equality-passes boundary, SoD anchor, claim 422, clock default, lot-status precedence, etc.)
- Contract 3 (§3 Path Purity): PASS — 501 backtick tokens scanned in §3, zero path/method violations

Note: two early audit runs reported phantom mass-missing fields — an artifact of the audit script itself (naive backtick pairing broke on §2.2's verbatim fenced JSON blocks, and `'## 3.'` substring-splitting matched `### 3.4.` headings). After stripping fenced blocks and using line-anchored section splits, the PRD itself verified clean; one genuine gap was found and fixed (`posture` now backticked in §2.8/§3.2).

## Step 5: Generate Unit Tests — 2026-08-13T14:45:00.000Z

Generation complete and audited. Summary:

## Tests emitted

**90 tests total** across 11 files in `test_suite/` (test_01_customers_and_rate_cards through test_11_security_and_rbac):

- **Queue A (Difficulty): 54 tests** — all 27 instances covered with exactly 2 tests each, tagged `Design: Difficulty/<rule_id>/<name>`.
- **Queue B (Corner): 36 tests** — one test per non-stub instance, tagged `Design: Corner/<section>/<name>`.

## Instances skipped (2)

- **Corner/endpoints/`allocate_on_already_allocated_order_rejected`** — fails unique derivability. PRD §3.5 describes allocate only from SUBMITTED (initial fill) and SHORTED (top-up) and never pins ALLOCATED as an invalid from-state; a faithful PRD-only reader could implement allocate on an ALLOCATED order as a legal no-op (gap = requested − allocated = 0) returning 200 instead of `ERR_INVALID_STATE`. No test emitted; gap stays a gap.
- **12 `excluded_because:` corner stubs** — not translated per spec; all cross-references verified to resolve to real difficulty instances.

## One recipe correction (not a skip)

- **Difficulty/compensating_invariant/`allocate_then_amend_conserves_pallet_counts`** — the recipe as written (order for 2 against 3 pallets → ALLOCATED, then amend) contradicts PRD §3.5 ("Amendment ... while the order stands at `DRAFT` or `SHORTED`; any other state rejects the amend"). I preserved the instance's invariant claim but routed it through the legal path: order for 4 against 3 pallets → SHORTED(3) → amend → DRAFT(0), asserting the same conserved quantities (zone `in_use_pallets`/`free_pallets`, lot `on_hand_pallets`). Same tag, same design instance.

## Deliberate assertion choices (PRD-silence handling)

- Timestamp equality (`period_start`, `last_blast_frozen_at`) uses instant comparison (`assert_instant_equals`) rather than string equality, since PRD pins the instant but not the fractional-digit rendering.
- Version assertions are relative (+1 per mutation, reads unchanged) rather than hard-coding initial `version == 1`, which PRD §2.5 does not pin.
- In `zone_capacity_exceeded_on_over_receipt_putaway`, the sub-assertion that the reservation is retained after a *rejected* completion was dropped (PRD describes reservation release only on the success path; rollback-on-error is not uniquely derivable). The error id, receipt-stays-ARRIVED, and `in_use_pallets == 3` assertions are kept.

## test_helpers/ files created

All under `/home/ubuntu/github/CodingPRD/tasks/task_1488_public_refrigerated_warehousing/test_helpers/`:
- `types.py` — 14 entity TypedDicts + 15 status/role enums (all entities carry common fields)
- `api_client.py` — `ApiClient(GenericApiClient)` with 49 endpoint methods covering every PRD §4 endpoint, all under `/api`
- `api_errors.py` — 24 `ApiErrorId` values + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity asserts + `assert_instant_equals` + `assert_invoice_total_invariant`
- `factories.py` — 11 payload factories (standard card "A" rates as defaults)
- `constants.py` — clock default, standard card, dwell/volume/posture thresholds
- `test_users.py` — 5 role header constants + per-instance builders (`make_customer_admin_headers(customer_id)` for the entity-backed role, plus opaque-role builders for SoD scenarios)
- `fixtures.py` — composite setup chain: `create_customer_with_card`, `receive_stock`, `setup_stocked_account`, order lifecycle helpers (`create_submitted_order`/`create_allocated_order`), `report_excursion`/`confirm_excursion` with SoD-aware user ids, `setup_confirmed_excursion`, blast booking helpers, invoice helpers (`get_open_invoice`, `get_finalized_invoices`, `finalize_due_invoices`)
- `__init__.py` — barrel export

## Audit results

- All files compile; all 11 test modules import cleanly against the real framework.
- Tag audit: every difficulty instance ≥2 tests, every non-stub corner instance = 1 test, no untagged/dual-tagged/orphan tags.
- Citation audit: all 133 quoted PRD spans in docstrings survive a literal whitespace-normalized grep of `PRD.md`.
- No `skip`/`skipif`/`xfail` markers; no scaffold references in generated comments/docstrings.

## Step 6: Generate Implementation — 2026-08-13T14:45:00.000Z

Implementation complete and verified. Both smoke suites (103 + 121 assertions) pass against a fresh `start.sh` boot, covering the receipt→putaway→FIFO→ship chain, OCC, blast freezing, excursion/recall cascades, claims, billing runs, storage/dwell math across four months, volume-discount tiers, and validation-tier precedence.

## Files created

All under `/home/ubuntu/github/CodingPRD/tasks/task_1488_public_refrigerated_warehousing/workspace/implementation/`:

- `start.sh` — reads `$PORT` (default 10000), guarded `pip install` (no-op once flask is importable), `exec python3 app.py` in foreground
- `requirements.txt` — `flask>=3.0`
- `app.py` — entry point, error-handler registration, blueprint wiring, `app.run(host="0.0.0.0", port=$PORT)`
- `core.py` — logical clock (boots at exactly `2026-08-01T00:00:00Z`), envelope helpers (`meta`/`response_type`/`data`, pagination fields `limit`/`offset`/`total_count`/`has_more`), `ApiError`, field/schema validators, auth (`X-User-ID`/`X-User-Role`), in-memory `DB` dicts, `new_record`/`touch` (version bump + `updated_at`)
- `views.py` — computed fields (zone posture, lot compound status, allocated counts, outstanding balance, invoice total) and all calculation rules in `Decimal` with `ROUND_HALF_UP`
- `routes_a.py` — clock, customers, rate cards, zones, inbound receipts
- `routes_b.py` — lots, pallets, outbound orders, allocations
- `routes_c.py` — cells, bookings, excursions, recalls, claims, invoices, billing run

**Endpoint count: 68** (matches the scaffold endpoint table exactly). Storage is purely in-memory dicts; nothing is seeded at boot; every resource starts empty and the store is rebuilt per process.

## Design decisions where the PRD was ambiguous

1. **Receipt-complete check-order conflict** — PRD §3.2's narrative mentions rate-card before capacity, but §2.9's global tier cascade puts capacity/consistency (tier 9) before fiscal (tier 11). I followed the tier cascade: schema → state → zone capacity → lot production-date → rate card.
2. **Order submit** — PRD §3.5 explicitly pins a gate order that contradicts the generic tiers (suspended/rate-card *before* the tier-7 `ERR_LOT_RECALLED`). Followed the pinned order: state → `ERR_CUSTOMER_SUSPENDED` → `ERR_NO_ACTIVE_RATE_CARD` → lot exists (404) → `ERR_LOT_RECALLED` → estimate → credit check.
3. **Duplicate `zone_code`/`cell_code`** — no dedicated error ID exists in the catalog; treated uniqueness as body-schema validation → `ERR_VALIDATION` (400).
4. **Zone/lot version bumps on derived-field changes** — zone `in_use/reserved/free/posture` and lot `on_hand/status` are computed on read from pallet/receipt state (per the aggregation formulas), so zone/lot `version` is not bumped by cascades; explicit bumps happen only where the PRD names them (e.g., Customer on rate-card supersede) and on any stored-field mutation.
5. **CustomerAdmin read of excursions/zones/cells** — these have no `customer_id`, so ownership scoping is impossible; all roles may read them. Customer-scoped resources (incl. allocations via their order) are ownership-filtered for CustomerAdmin on both reads and lists.
6. **Out-of-range `limit`/`offset`** — rejected with `ERR_VALIDATION` (400) rather than clamped, since the scaffold declares min/max bounds.
7. **Billing run with overdue successor** — a run finalizes the snapshot of OPEN invoices due at entry and creates one next-month OPEN successor per finalized invoice; a successor whose `period_end` is also already past waits for the next run (matches "finalizes every OPEN invoice whose period_end <= now, then opens successor").
8. **Ship with no ACTIVE rate card** — unreachable in practice (submit requires one and supersession always leaves one ACTIVE), but coded defensively to a zero fee rather than `ERR_NO_ACTIVE_RATE_CARD`, since §2.10 names only four card-gated charging events and ship is not among them.
9. **Order amend with no ACTIVE rate card** — returns `ERR_NO_ACTIVE_RATE_CARD` (amend re-prices the estimate, and tier 11's `applies_to` includes order amend).
10. **`api_request_timestamp`** — sourced from the logical clock (the PRD says the server never reads wall-clock time), formatted with exactly 3 fractional digits and `Z`.

## Step 7: Test/Iterate Loop — 2026-08-13T15:50:00.000Z

Iteration 1 sweep (8 parallel rounds, per-test-server isolation): 89/90 in all 8 rounds.
Union of failures: `test_daily_prorated_charges_present_days` (deterministic, all rounds) — `assert 3100 == 2700`.

Diagnosis (STEP 1+2): PRD §3.9 verbatim-covers the DAILY_PRORATED formula and the received_at presence rule (uniquely derivable — test kept). The test's `_setup_variant_pair` never advanced the logical clock from its 2026-08-01 startup default before `receive_stock`, so pallets were stamped `received_at` = 2026-08-01 (31 present days → 3100¢) instead of the intended 2026-08-05 (27 days → 2700¢). Implementation was PRD-correct; the test setup was the bug (its own docstring says "received 2026-08-05"; sister helper `_setup_one_day_pallets` advances the clock correctly).

Fix (test_suite only): `test_10_billing_and_invoices.py::_setup_variant_pair` — added `set_clock("2026-08-05T08:30:00Z")` before the two `receive_stock` calls.

Iteration 2 sweep: **90/90 in all 8 rounds — clean.**

## Step 8: Finalize PRD — 2026-08-13T15:46:00.000Z

Step 8 complete. `PRD_FINALIZED.md` exists at `/home/ubuntu/github/CodingPRD/tasks/task_1488_public_refrigerated_warehousing/workspace/PRD_FINALIZED.md` and is byte-identical to `PRD.md` — **zero edits were committed**, and that is the verified-correct outcome, not an oversight.

## Summary

**Line counts / delta:** PRD.md = 329 lines; PRD_FINALIZED.md = 329 lines; 0% delta (diff confirms identical).

**Changes:** None.

**Why zero edits is correct — verification evidence per the single Step 7 item:**

The only Step 7 fix was a test-suite fixture fix (`test_10_billing_and_invoices.py`, `TestStorageMethodVariants._setup_variant_pair`: added `set_clock("2026-08-05T08:30:00Z")` before two `receive_stock` calls). No tests deleted, no `test_helpers/` fixes, no `implementation/` fixes. I traced every behavior that item touches and confirmed each is already uniquely pinned by PRD-verbatim prose:

- **Logical clock startup value** — PRD §2.4: "At startup the clock reads exactly 2026-08-01T00:00:00Z, and it never consults wall-clock time." Impl: `core.py:21` (`CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}`). Match.
- **Clock endpoint contract** — PRD §2.4: accepts `to_iso8601`, responds with `current_utc`, available to all five roles; "'now'... means this logical clock." Impl: `routes_a.py:29-37`. Match.
- **`received_at` stamping** — PRD §3.2: pallets created at receipt completion with "`received_at` set to now." Impl: `routes_a.py:364,373` (`now = clock_now()`; `"received_at": now`). Match — this is exactly the behavior the unfixed test violated by never advancing the clock from its startup default.
- **Presence-day counting** — PRD §3.9: "the date of its `received_at` on or before that date, and either `out_at` null or the date of `out_at` strictly after that date" over dates in `[period_start, period_end)`. Impl: `views.py:170-182`. Match.
- **DAILY_PRORATED formula** — PRD §3.9: "present-days count multiplied by the class rate and divided by thirty, rounded half up to whole cents." Impl: `views.py:186-187` (`Decimal(days * rate) / Decimal(30)`, `ROUND_HALF_UP`). Match (27 days × 3000¢ / 30 = 2700¢ as the fixed test asserts; 31 days → 3100¢ under the un-advanced clock, which is what the buggy fixture observed).
- **Per-pallet rounding order** — PRD §2.6 explicitly pins per-pallet rounding before summing and rejects the sum-then-round reading. Impl: `views.py:187,190` (quantize per line, then `total += line`). Match.
- **FULL_MONTH variant** — PRD §3.9: "full monthly class rate when the pallet was present at least one day... zero otherwise." Impl: `views.py:183-184,188-189`. Match.
- **Billing-run finalization flow** — PRD §3.9 (eligibility `period_end` reached/passed, zero-rate computation with no ACTIVE card, `rate_card_id` recording, successor OPEN invoice, `finalized_count`/`finalized_invoice_ids` response). Impl: `routes_c.py:651-676` plus `views.py:165-169,197`. Match.

The Step 7 diagnosis classified this as a pure fixture bug against PRD-verbatim-covered behavior (STEP 1a/1b passed — uniquely derivable), and my independent read of `core.py`, `views.py`, `routes_a.py`, and `routes_c.py` confirms it. No PRD silence and no PRD/impl mismatch exists at the Step 7 site, so per the hard scope rule no wording change is owed. The NO-NEW-MISMATCH pre-edit search is trivially satisfied: with zero edits there are no subjects to enumerate, and the verification reads above double as confirmation that the untouched prose accurately describes every implementation path it governs.

## Step 9: PRD Completeness Scan — 2026-08-13T15:58:00.000Z

Done. `PRD_COMPLETED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_1488_public_refrigerated_warehousing/workspace/PRD_COMPLETED.md`.

**Source vs output:** PRD_FINALIZED.md (329 lines / 51,503 chars) → PRD_COMPLETED.md (329 lines / 52,854 chars), char-delta +1,351. All changes are inline; no sections added or removed. PRD_FINALIZED.md was byte-identical to PRD.md.

**Counts:** 11 ambiguity-pins, 1 mismatch-revision (12 changes total).

**Changes:**

- §2.1 — revise — mismatch — dropped `excursions` from the CustomerAdmin ownership-scoped read list and added that excursions are zone-scoped (no `customer_id`) and readable by any authenticated role — `routes_c.py:231-249` (get/list excursion perform no `check_ownership`/customer filter).
- §2.3 — insert — ambiguity — pinned that a non-integer or out-of-range `limit` (outside 1–100) and a non-integer or negative `offset` are rejected `ERR_VALIDATION` — `core.py:175-194`.
- §2.3 — insert — ambiguity — pinned list-ordering tie-break: creation-timestamp ties broken by record creation sequence — `core.py:199` (`sorted(..., key=(created_at, _seq))`).
- §2.3 — insert — ambiguity — pinned `has_more` semantics: true exactly when `offset` + page size < `total_count` — `core.py:92`.
- §2.5 — insert — ambiguity — pinned `version` starts at 1 at resource creation — `core.py:261`.
- §2.8 — insert — ambiguity — pinned posture is `FULL` when `free_pallets` is zero *or negative* (an arrival reservation larger than remaining free capacity can drive it negative) — `views.py:109` (`free <= 0`), `routes_a.py:307-320`.
- §3.2 — insert — ambiguity — pinned duplicate `zone_code` rejected with `ERR_VALIDATION` — `routes_a.py:188-189`.
- §3.4 — insert — ambiguity — pinned duplicate `cell_code` rejected with `ERR_VALIDATION` — `routes_c.py:34-35`.
- §3.4 — insert — ambiguity — pinned booking pallet-selector final tie-break by creation sequence after `received_at`/`created_at` — `routes_c.py:145-149`.
- §3.5 — insert — ambiguity — pinned `estimated_handling_out_cents` is null from order creation until first submit/amend — `routes_b.py:180`.
- §3.5 — insert — ambiguity — pinned FIFO allocation final tie-break by creation sequence after `production_date`/`received_at`/`created_at` (pallet id never used) — `routes_b.py:149-150`.
- §3.5 — insert — ambiguity — pinned ship with no ACTIVE rate card: final fee is zero and the ship proceeds (ship is not one of the four card-requiring events) — `routes_b.py:306-307`.
- §3.6 — insert — ambiguity — pinned `observed_temp_c` accepts any JSON number (integer or decimal), stored and echoed exactly as supplied — `routes_c.py:211`, `core.py:169-172`.
- §3.9 — insert — ambiguity — pinned finalized invoice's `rate_card_id` is recorded as null when no card is ACTIVE at run time — `routes_c.py:668`.

**Verified already-pinned (no change needed):** all 68 endpoints with roles and 201/200 split; full validation-tier cascade order (auth → schema → role → ownership → existence → state/OCC → food-safety → temporal → capacity → claim refs → fiscal); logical clock start and setter response shape; envelope/meta fields; lot compound-status precedence; excursion overlap formula and 4-hop cascade; recall cascade; claim cross-reference gates (incl. 422); volume-discount tiers and strict-greater credit check; per-pallet round-half-up storage/dwell math; billing-run eligibility (`period_end <= now`), zero-eligible success, successor-invoice opening; error catalogue HTTP statuses (all 24 match impl exactly).
