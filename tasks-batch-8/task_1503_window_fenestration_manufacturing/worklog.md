# Worklog — task_1503_window_fenestration_manufacturing

## Step 1: Create Task Directory — 2026-08-13T14:33:00.000Z

Task directory `tasks/task_1503_window_fenestration_manufacturing/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE. Verified existence via `ls`. Difficulty directive from launcher: "harder than expert level" — forwarded to scaffold generator.

## Step 2: Generate Scaffold — 2026-08-13T16:06:00.000Z

Scaffold generation complete. All three files are written and lint-clean.

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1503_window_fenestration_manufacturing/SCAFFOLD.yaml` (§1.0–§1.7 + complexity_profile + domain_constants; 84.9 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_1503_window_fenestration_manufacturing/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top key `scaffold_difficulty_design`; 95.0 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_1503_window_fenestration_manufacturing/SCAFFOLD_CORNER_DESIGN.yaml` (single top key `scaffold_corner_design`; 162.4 KB)

## Counts
- Entities: 13 · Endpoints: 68 · Error codes: 31 · Calculations: 12 · State machines: 11 · Validation priority rows: 11 · Roles: 6 · OCC concurrency rules: 2
- §1.8: 22 instances (rules 1–9: 2/3/2/2/3/3/3/2/2 — all minimums met or exceeded)
- §1.9: 64 instances (51 full test recipes + 13 `excluded_because` stubs) across all 9 claim-guide sections
- Lint verdict (verbatim tail): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1067 calls scanned)

## Design decisions of note
1. **RackReservation split mid-design**: a single-active-reservation rack machine made the Rule-8 occupancy rule unreachable (the state precondition would always fire before overlap detection). Reservations became a first-class entity; multiple reservations coexist per rack, enabling closed-interval + 1-day-turnover-buffer semantics — structurally contrasted with EnergyCodeRule's half-open, adjacency-allowed windows (order dated exactly at a window boundary selects the new rule).
2. **Depth-3 cascade**: `wave_auto_unlock` (allocated_units < ceil(capacity/2) ⇒ LOCKED/RELEASED → OPEN) turns IG breakage into unit→line GLASS_HOLD→allocation release→wave reopen. Resume requires wave RELEASED again, so remake cycles exercise lock→release→resume interleavings (remake-limit corner replays this 3×).
3. **Rule-1 domains**: NFRC rating dual-variant on EnergyLabel (catalog vs worst-unit argon derate; 0.28 vs 0.30 with a compliance flip risk at the 0.30 boundary) and warranty coverage on WarrantyClaim (COMPONENT vs WHOLE_UNIT windows; HARDWARE year-8 → 100 vs 40).
4. **Rule-2 modes all distinct**: (a) line pricing with shape multiplier × min-billable max() × adders; (b) per-line-round-then-sum (140050 vs 140051 one-cent discriminator, A050/1999-rate/33% upcharge crafted to produce fractional cents); (c) volume-discount tier keyed on pre-discount subtotal (subtotal 2145039 → 8% even though post-discount 1973436 sits in the 5% tier).
5. **OCC ordering**: `expected_*_version` checked at priority 6, before state preconditions at 7 — the precedence itself is corner-tested (`stale_version_beats_state_on_line_patch`). All OCC payloads use `${var}`/expression form.
6. **All numeric asserts pre-executed** via Python/Decimal (including the CIRCLE 4.91-sqft glazing and the PATCH reprice 192080→143300, where the area factor reverts 0.85→1.0); logical clock endpoint declared with the mandatory 2026-08-01T00:00:00Z startup default, used to age deliveries 8 years for warranty claims.

## Step 3: Copy Shared Files — 2026-08-13T16:07:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1503_window_fenestration_manufacturing/workspace/INSTRUCTION.md`. Verified present.

## Step 4: Generate PRD — 2026-08-13T16:35:00.000Z

All checks pass. The PRD is complete and verified.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1503_window_fenestration_manufacturing/workspace/PRD.md` (346 lines)

**Section list:**
- §1 Introduction (2 paragraphs: dealer-to-delivery business chain + system scope, parallel production/compliance dimensions, logical clock)
- §2 Global Specifications (10 subsections): 2.1 RBAC, 2.2 API Response Structure (byte-identical to the fixed source block), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 The Logical Clock, 2.6 Nested Resource Retrieval, 2.7 Money/Measurements/Rounding, 2.8 Optimistic Concurrency Control, 2.9 Cascades/Bubble-Ups/Derived State, 2.10 Request Validation Pipeline (all 11 scaffold priority stages in order)
- §3 Business Logic (8 subsections): 3.1 Dealer Accounts & Catalog Foundations, 3.2 Order Configuration & Pricing, 3.3 Energy Code Rules & Labels, 3.4 Production Waves & Release, 3.5 IG Fabrication/QC/Remake Cycle, 3.6 Racks/Reservations/Delivery, 3.7 Warranty Claims & Service Parts, 3.8 Cancellation Paths
- §4 Endpoint Definitions (68 rows, 4 columns), §5 Error Code Catalogue (31 rows, 2 columns)

**Zero-Silence coverage audit (every scaffold rule → PRD passage):**
- **Contract 1 (Field-Name Coverage): PASS** — 105/105 required identifiers present in backticks (all entity fields, all endpoint inputs incl. `to_iso8601`/`expected_wave_version`/`expected_order_version`, all query-filter params, envelope/header fields); all 6 role names, 43 state values, 31 enum values, and all 31 error IDs present.
- **Contract 2 (Rule Coverage): PASS** — 57 targeted rule checks verified: both OCC rules (endpoint + occ field + `ERR_STALE_VERSION`/412 + stale-read framing); 12 calculations as reconstructible prose (line pricing with shape/grid/hardware constants, pinned subtotal rounding order, discount tiers 500k/2M/5M → 5/8/12% with no tier feedback, provisional vs certified NFRC dual variant with 0.002 argon derate and spacer derates, half-open rule selection with inclusive bounds, wave allocation with counted-line filter, strict half-capacity auto-unlock, closed-interval + 1-day-buffer rack overlap, lead-time promise, COMPONENT vs WHOLE_UNIT warranty decay with 365-day year floor, carrier fees, argon QC dual gate); 11-stage validation pipeline stated with explicit cross-gate precedence (`ERR_ENERGY_CODE_VIOLATION` before `ERR_DEALER_CREDIT_HOLD`; OCC before state before capacity); all state transitions incl. sibling symmetry (4 cancel paths, 4 close paths, 4 breakage stages, 3-hop GLASS_HOLD cascade, release idempotency, unreachable CERTIFIED→PROVISIONAL noted); all cross-entity cascades and field defaults.
- **Contract 3 (§3 Path Purity): PASS** — 563 §3 backtick tokens scanned, zero paths/methods/method+path tokens.
- No fuzzy/approximating words (the two `about` hits are non-numeric usages), no pseudocode operators outside the fixed §2.2 JSON block, no invented rules; the withheld difficulty/corner design files were never opened.

## Step 5: Generate Unit Tests — 2026-08-13T17:28:00.000Z

Done. Test infrastructure and suite generated for `task_1503_window_fenestration_manufacturing`.

## Files written

**test_helpers/** (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1503_window_fenestration_manufacturing/test_helpers/`):
- `types.py` — 13 entity TypedDicts (all carry `id/created_at/updated_at/version` per PRD §2.4), 20 status/field enums, `UserRole`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (incl. root-level `/_clock/set_current_utc`, not under `/fenestration`)
- `api_errors.py` — all 31 error IDs + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions
- `constants.py` — shape area factors, grid/hardware adders, discount tier floors, argon/spacer derates, remake cap 3, warranty windows, carrier fees, canonical V200/A050/GP1/GP3/MN/AZ payloads and dates
- `factories.py`, `test_users.py` (shared role headers + `make_dealer_rep_headers(dealer_id)` for the entity-backed DealerRep), `fixtures.py` (composite chains: `setup_mn_catalog`, `setup_confirmed_order`, `setup_order_in_production`, `setup_completed_order`, `setup_shipped_order`, `setup_delivered_order`, `setup_claim_under_review`, OCC-safe `assign_order`, `produce_line`, `find_remake_of`, etc.)

**test_suite/** (12 files): `conftest.py` + 11 test files organized by concern (intake, pricing, energy labels, confirmation pipeline, waves, IG/remake, cascades, racks, claims, shipments, security/RBAC).

## Test counts
- **Queue A (Difficulty): 44 tests** — all 22 instances × exactly 2 tests each
- **Queue B (Corner): 51 tests** — all 51 non-stub instances × 1 test each
- **95 total**, collected cleanly by pytest

## Skipped instances
None. Every non-stub instance passed the PRD-first two-condition filter. The 13 `excluded_because:` corner stubs were not translated; all their `difficulty_instance` cross-references resolve to real queue-A instances.

One deliberate relaxation (not a skip): two corner instances (`dealer_created_with_credit_active_default`, `wave_create_computed_input_ignored`) and one consistency instance assert literal `version == 1`. PRD §2.4 says version "increments by one with every modification" but never pins the initial value, so a PRD-only reader could start at 0 — the version assertion is `isinstance(int)`; all other asserted outcomes (credit_status ACTIVE, allocated 0, PLANNED, logical-clock `created_at` prefix) are verbatim-derived and kept.

## Stage 2 self-check verdict
- Tag audit: every one of 95 tests carries exactly one `Design:` line; all resolve to real `name:` entries; no tag points at a stub. ✓
- Citation audit: scripted verbatim check — every quoted docstring citation has a ≥8-word substring surviving literal grep of `workspace/PRD.md` (0 failures). ✓
- No `skip`/`skipif`/`xfail` markers; no scaffold/Table references in generated code. ✓
- Priority-pair instances were testable because PRD §2.10 explicitly pins pipeline order (including the exact energy-vs-credit example), so they were translated, not skipped.

## Step 6: Generate Implementation — 2026-08-13T17:28:30.000Z

Implementation complete. Summary below.

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_1503_window_fenestration_manufacturing/workspace/implementation/`:

- `start.sh` — foreground launcher; guarded `pip install` (no-op once Flask importable); `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=2.2`
- `app.py` — Flask app factory, ApiError/404/405/500 handlers (all emit the scaffold envelope), blueprint registration
- `store.py` — in-memory dict store + logical clock (starts exactly `2026-08-01T00:00:00Z`, never wall-clock); zero seeding
- `common.py` — response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields inside `meta`), `ApiError`, Decimal half-up helpers, ISO-8601 parse/format, body validators, `require_roles` auth (X-User-ID / X-User-Role, six roles), ownership check
- `services.py` — domain engine: line pricing, subtotal/discount tiers, NFRC provisional/certified ratings, rule selection, wave allocation + auto-unlock, rack recompute, breakage/QC cascade with auto-remake + remake depth cap, cancel cascade, warranty coverage (both variants), all serializers
- `routes_admin.py`, `routes_orders.py`, `routes_production.py`, `routes_shipping.py`, `routes_warranty.py` — the 68 endpoints

## Endpoint count

**68/68** endpoints from the scaffold §1.5 table implemented.

## Verification performed

- `bash start.sh` from `./implementation/` boots to HTTP-ready in ~0.6s; reboot wipes all state (old IDs 404) — per-test-server isolation contract verified
- Three smoke suites (~150 assertions, all passing on fresh boots): full lifecycle (dealer → series/glass → rule → order → line → confirm → wave assign/lock/release → IG advance/QC → breakage/remake/GLASS_HOLD/resume → rack reserve/load/ship → delivery → claim → approve → shipment → fulfill), plus edge cases: stale-version 412 precedence, credit-hold/energy-violation ordering at confirm, capacity equality boundaries, lead-time gate, turnover-day occupancy conflicts, remake limit (3) atomicity, certified-U code gate at QC boundary, ownership 403s, duplicate active claims, warranty coverage schedules, pagination validation.

## Interpretation decisions (PRD ambiguity → choice)

1. **Ownership on reads** — §2.10 stage 3 says ownership applies to "DealerRep-accessible order, line, and claim endpoints" without excluding GETs, while RBAC says GETs are "any authenticated role" → I enforce `ERR_OWNERSHIP_MISMATCH` for DealerRep on single-resource GETs and sub-collections of orders/lines/claims (and their nested label/IG/claim-shipment views), but not on plant-wide list endpoints (filters only, no 403).
2. **Pagination out-of-range** — "minimum of 1 and a maximum of 100" → rejected with `ERR_INVALID_REQUEST` (400) rather than clamped; non-integer `limit`/`offset` also 400.
3. **Cancel of IN_PROGRESS order by DealerRep** — endpoint allows DealerRep generally but the IN_PROGRESS transition is "PlantManager only" → `ERR_FORBIDDEN_ROLE` (403).
4. **Order totals on cancel** — calc trigger table lists "line cancel" for subtotal/promised recompute → cancelled orders recompute to zero totals/null promised_date (per the trigger, even though confirm "freezes" prices).
5. **CLAIM_NOT_REVIEWABLE scope** — PRD names only take-review/request-info/approve/deny for that error → `provide-info` and `appeal` from wrong states return generic `ERR_INVALID_STATE`.
6. **`current_utc` / domain datetime rendering** — whole-second values render as `...Z` (echoing the PRD's default clock string `2026-08-01T00:00:00Z`); fractional values render with 3 digits. `created_at`/`updated_at`/`api_request_timestamp` always render 3 fractional digits per PRD §2.4/§2.2 examples. All server timestamps use the logical clock.
7. **Remake `unit_index`** — copied from the broken unit (field is documented as "1..quantity within the line").
8. **`argon_measured_pct` on QC failure** — recorded on the BROKEN unit (scaffold only pins recording on pass, but the measurement occurred; certified rating only reads QC_PASSED units so this is inert).
9. **Uniqueness of `series_code`/`code`/`rack_code`** — described as "unique" but no error ID exists for duplicates → not enforced.
10. **Wave version bumps** — assignment/unassign bump via the allocation recompute (one increment per request, matching "increments ProductionWave.version by 1"); cascade recomputes bump only when allocation or status actually changed.
11. **QC-check while line is GLASS_HOLD** — allowed (scaffold lists no line-state precondition for qc-check, unlike advance which requires IN_PRODUCTION).
12. **`ERR_SIZE_EXCEEDS_SERIES_LIMIT` (422) ordering** — checked after `ERR_SERIES_DISCONTINUED`, both within business-constraint stage, following the scaffold's listed order.

## Step 7: Run Tests and Iterate — 2026-08-13T17:35:00.000Z

All 8 parallel rounds are fully clean on the first sweep — no fixes or deletions were needed.

Summary:
- **Iterations run**: 1 (single 8-round parallel stability sweep; every round ran to completion).
- **Results**: All 8 rounds report `total=95, passed=95, failed=0, errors=0, skipped=0`. No flakiness observed across rounds 1–8.
- **Tests deleted**: none.
- **Fixes applied to `test_helpers/`**: none.
- **Fixes applied to `implementation/`**: none.

The task at `/home/ubuntu/github/CodingPRD/tasks/task_1503_window_fenestration_manufacturing` is stable: 95/95 tests passing in every one of the 8 concurrent rounds under `--isolation per-test-server`.

## Step 8: Finalize PRD — 2026-08-13T17:35:30.000Z

SKIPPED per the skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced.

## Step 9: Complete PRD — 2026-08-13T17:52:00.000Z

PRD_COMPLETED.md written at `/home/ubuntu/github/CodingPRD/tasks/task_1503_window_fenestration_manufacturing/workspace/PRD_COMPLETED.md`. I walked all 8 implementation files (`app.py`, `common.py`, `store.py`, `services.py`, `routes_admin.py`, `routes_orders.py`, `routes_production.py`, `routes_shipping.py`, `routes_warranty.py`) exhaustively — every route, state transition, calculation, validation order, and serializer field — and classified each behavior against the PRD.

## Summary

**Size:** PRD.md 346 lines / 54,919 chars → PRD_COMPLETED.md 346 lines / 58,949 chars (char-delta +4,030; zero lines added or removed — all 21 edits are inline in-paragraph inserts/revisions, no new sections).

**Counts:** 17 ambiguity-pins, 4 mismatch-revisions (21 changed paragraphs total).

**Changes:**

- §2.2 — insert — ambiguity — transition/mutation endpoints return the resource the path addresses (wave ops return the ProductionWave, line ops the OrderLine, reservation ops the RackReservation, clock returns `current_utc`) — routes_production.py:87,106; routes_shipping.py:132,159,174
- §2.3 — insert — ambiguity — non-integer `limit`/`offset`, `limit` outside 1–100, or negative `offset` rejected with `ERR_INVALID_REQUEST` (400) — common.py:125-142
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — store.py:53
- §2.5 — revise — ambiguity — clock set has no monotonicity constraint (may move backward); logical clock also stamps every `created_at`/`updated_at` and `meta.api_request_timestamp` — routes_admin.py:21; store.py:47-50,59-61; common.py:91-95
- §2.10 stage 3 — insert — ambiguity — ownership enforced only on order/line/claim-anchored single reads, per-parent nested lists, and dealer-scoped mutations; direct-by-id EnergyLabel/IGUnit/ServicePartShipment reads and all plant-wide collection lists are unfiltered — routes_orders.py:94-109,216-235,314-329; routes_production.py:201-216; routes_warranty.py:217-231
- §3.1 — revise — ambiguity — `ship_to_state_code` stored unvalidated; credit-hold/release each defined only from their source state, else `ERR_INVALID_STATE` — routes_admin.py:32,44-63
- §3.1 — revise — mismatch — `series_code` uniqueness not enforced (duplicates accepted) — routes_admin.py:72-85
- §3.1 — revise — mismatch — GlassPackage `code` uniqueness not enforced — routes_admin.py:109-126
- §3.2 — revise — ambiguity — `width_in`/`height_in` accept any positive number (fractional allowed); `quantity` must be an integer ≥ 1 — routes_orders.py:41-53
- §3.3 — insert — ambiguity — no ordering constraint between `effective_from` and `effective_to` is enforced — routes_admin.py:144-147
- §3.3 — revise — mismatch — `compliance` is evaluated at line creation (PASS/FAIL when a rule applies), not "begins UNEVALUATED" — routes_orders.py:197-203; services.py:136-149
- §3.3 — revise — ambiguity — argon derate is signed: overfill above `argon_target_pct` lowers the certified U-factor symmetrically, no clamp at zero — services.py:152-155
- §3.4 — revise — ambiguity — unassign also rejects an order RELEASED on a different wave (`ERR_INVALID_STATE`) — routes_production.py:97-99
- §3.5 — revise — ambiguity — QC code gate uses the same signed derate — routes_production.py:253-254
- §3.5 — revise — ambiguity — QC failure records the failing `argon_measured_pct` on the BROKEN unit and the endpoint still returns 200 with the unit — services.py:285-286; routes_production.py:264-266
- §3.5 — revise — ambiguity — auto-remake inherits the broken unit's `unit_index` and `spacer_type` (argon/break_cause null); remake-limit rejection is atomic, leaving the unit unchanged — services.py:282-299
- §3.6 — revise — mismatch — `rack_code` uniqueness not enforced — routes_shipping.py:17-25
- §3.6 — revise — ambiguity — no ordering constraint enforced between `load_date` and `ship_date`; reservation on an order not IN_PROGRESS/COMPLETED is `ERR_INVALID_STATE` — routes_shipping.py:54-58
- §3.7 — insert — ambiguity — `order_line_id` must belong to the named order, else `ERR_NOT_FOUND` — routes_warranty.py:36-37
- §3.8 — revise — ambiguity — cancellation defined only from DRAFT/CONFIRMED/RELEASED/IN_PROGRESS (SHIPPED/COMPLETED also yield `ERR_INVALID_STATE`); cancellation recomputes order money fields and `promised_date` over surviving lines (zeroing totals when none survive) — services.py:313-340
- §3.8 — revise — ambiguity — IN_PROGRESS cancellation also clears the order's `wave_id`, exactly as the RELEASED path — services.py:334-336

Everything else in the implementation — pricing formula and rounding order, discount tiers, energy-rule half-open window selection, QC gates, wave capacity/lead-time/auto-unlock rules, rack occupancy 2-day turnover, warranty coverage curves and remedy computation, RBAC table, pipeline ordering, and error catalogue — was already uniquely pinned by the PRD and left untouched.
