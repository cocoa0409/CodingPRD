# Worklog — task_2483_microtransit_on_demand_transit_service

## Step 1: Create task directory — 2026-09-02T23:50:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2483_microtransit_on_demand_transit_service` and `.../workspace` using the pre-assigned path (no index auto-allocation, per orchestration instructions).

## Step 2: Generate scaffold — 2026-09-03T01:24:00.000Z

Scaffold generation for task 2483 is complete. All three files are written and the linter is clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2483_microtransit_on_demand_transit_service/`): `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`. Generated purely from the scenario text plus the scaffold-generator skill; no sibling task directory was read.

**Domain**: Microtransit & On-Demand Transit Service. `primary_archetype: temporal_windowing`, `secondary_archetype: pricing_engine`, `entity_topology: flat`, `state_machine_shape: cyclic`, `role_model: segregation_of_duties`, `consistency_model: immediate`, `complexity_layers: [selector_policy, dual_variant_calculation, cascading_side_effects, optimistic_concurrency]`.

**§1.1 Entities (12)**: ServiceZone, VirtualStop, TransitConnection, Vehicle, Driver, Rider, DemandForecast, VehicleBlock, TripRequest, PoolAssignment, FareTransaction (immutable ledger, `common_fields: false`), SubsidyReport.

**§1.2 State machines (10)** over 9 entities — TripRequest carries two dimensions (`status` RECEIVED→MATCHING⟲→OFFERED→ASSIGNED→PICKED_UP→COMPLETED / CANCELLED / NO_SERVICE, and `fare_status` UNPRICED→QUOTED→CAPPED/CHARGED→REFUNDED). SubsidyReport is cyclic (CERTIFIED→AMENDED→SUBMITTED→CERTIFIED); PoolAssignment branches OFFERED→{ACCEPTED, DECLINED, RELEASED}; DemandForecast has a system-only PUBLISHED→SUPERSEDED trigger.

**§1.2.1 Concurrency rules (2)**: `offer-create-stale-block` (POST /pool-assignments, `expected_vehicle_block_version` → ERR_STALE_VEHICLE_BLOCK_VERSION 412) and `forecast-create-stale-zone` (POST /demand-forecasts, `expected_service_zone_version` → ERR_STALE_SERVICE_ZONE_VERSION 412).

**§1.3 Calculations (6)**: corridor_travel_geometry, pool_match_selection (weighted selector with pinned tie-break), trip_fare (dual variant PROVISIONAL_QUOTE / SETTLED_CHARGE, 8 pinned steps, distance-band surcharges, category multipliers, transfer credit, daily/weekly fare caps), fleet_sizing (base + peak-surge blocks, surge threshold 1.50 inclusive), subsidy_per_trip (dual variant PROVISIONAL / FINAL), service_performance_metrics (wait/ride means, boardings per revenue hour, WAV equivalence ratio + verdict).

**§1.4 Validations**: 35 rules on a strict priority ladder 1–58 (auth 1–3, path 404s 4, body FKs 5, ownership 6, shape 7, then domain rules 8–58 including walk-distance 26, WAV accessibility 27/28, equivalence 30, vehicle half-open overlap 32, driver rest buffer 34, pickup-in-window 36, transfer window 38, curb 15-minute bucket 40, report period overlap 42, detour tolerance 44, seat 52, securement 54, fleet size 56, block finalization 58).

**§1.5 Endpoints (56)**: 32 POST + 24 GET, no PATCH/PUT/DELETE (immutable-append design); includes one test-driving endpoint `POST /_clock/set_current_utc`.

**§1.6 Errors (52)**. **§1.7 Roles (6)**: ZoneAdmin, Dispatcher, Rider (`entity_backed:Rider`), DriverUser (`entity_backed:Driver`), FinanceAnalyst, FundingAgencyAuditor.

**§1.8 SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 9 rule blocks, **25 instances** (2–3 per rule: dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 3, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 3, compensating_invariant 2).

**§1.9 SCAFFOLD_CORNER_DESIGN.yaml**: all 9 guide sections, **87 instances = 56 full `test_recipe`s + 31 `excluded_because` stubs** — entities 12, state_machines 17, calculations 14, validations 23, endpoints 6, errors 6, rbac 4, cross-cutting complexity layers 4, consistency model 1. Every stub cites an existing §1.8 instance by name; all 52 catalog errors are triggerable across the two design files.

**Linter verdict (verbatim)**:
```
Coverage
  §1.5 endpoints declared:    56
  §1.1 entities declared:     12
  §1.8 instances scanned:     25
  §1.9 instances scanned:     56
  Calls scanned (§1.8+§1.9):  1229

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Also verified independently: single correct top-level key per design file, no duplicate instance names across the union of both files, every instance carries `claim_type` + `grounds`, no instance carries both a recipe and a stub, and banned concurrency vocabulary was removed from the two places it had crept into prose.

## Step 3: Copy shared files — 2026-09-03T01:25:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md`. Verified scaffold line counts: SCAFFOLD.yaml 2147, SCAFFOLD_DIFFICULTY_DESIGN.yaml 2838, SCAFFOLD_CORNER_DESIGN.yaml 4061.

## Step 4: Generate PRD — 2026-09-03T01:38:00.000Z

PRD generated and verified at `workspace/PRD.md`.

**510 lines**, 25 headings, ending at a completed §5 table (no truncation, no audit footer).

Skeleton (domain-derived): §1 Introduction (3 paragraphs on equity of service, cost accountability, determinism). §2 — 2.1 Access Control · 2.2 API Response Structure (verbatim from shared fragment) · 2.3 Pagination · 2.4 Common Resource Properties · 2.5 The Logical Clock · 2.6 Corridor Geometry and the Travel-Time Model · 2.7 Numeric Precision and Rounding · 2.8 Stale-View Protection on Capacity-Bearing Writes · 2.9 Rejection Precedence (full 35-step ordering) · 2.10 Cascades, Ordering and Version Propagation · 2.11 Zone Scoping and Referential Integrity. §3 — 9 subsections: zone policy/stops/fixed-route anchors · fleet, roster, riders · demand forecasting and fleet sizing · scheduling and running blocks · trip intake and real-time matching · the driver's manifest · fares, transfer credit and capping · zone performance and equivalent service · subsidy reporting and certification. §4 — 56 rows, 4 columns. §5 — 52 rows, 2 columns.

Coverage reports (all PASS):
- Field coverage: entities[].fields 110/110; endpoints[].input 67/67; enum/state literals 61/61.
- Rule coverage: validations 35/35 (explicit ordered precedence in §2.9); concurrency_rules 2/2 (both 412 OCC errors with expected_* fields); state_machines 8 machines / 9 axes, all transitions with from/to, preconditions paired to error ids, all side effects incl. 4-hop block-cancel chain, 3-hop decline chain, 3-hop complete chain, zone-suspend sweep, driver-suspend sweep, stop-pairing sweep, forecast supersede; calculations 6/6 fully expressed with constants embedded in business context; endpoints 56/56 side effects + applies_to; entity structured content 110/110; sibling-branch symmetry 11 groups, 0 asymmetric.
- Path purity (§3 only): 855 backtick tokens scanned, 0 starting with `/`, 0 bare HTTP-method tokens, 0 method+path tokens. 0 tables and 0 schema/field lists inside §3; no fuzzy words; no pseudocode operators in prose.

Verbatim last 3 lines:
```
| `ERR_BLOCKS_NOT_FINALIZED` | 409 |
| `ERR_BLOCK_HAS_ACTIVE_ASSIGNMENTS` | 409 |
| `ERR_TRIP_NOT_CHARGED` | 409 |
```

Notes:
- Neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was opened, grepped, or referenced.
- Two internal scaffold tensions resolved toward the more concrete `endpoints[].side_effects` spec: (a) `TripRequest.baseline_direct_minutes` computed at intake *and* recomputed on every offer creation (create endpoint's null-list omits it); (b) subsidy-report reject/amend clear `submitted_by_user_id`, per the endpoint side-effect lists which are a superset of the state-machine entries.
- The `VirtualStop` pairing sweep is documented only on `APPROVED → RETIRED`, matching the scaffold exactly rather than symmetrising onto `PROPOSED → RETIRED`.
- Three preconditions with no dedicated error code (vehicle retire while a live block references it; block open with a non-`AVAILABLE` vehicle or non-`ACTIVE` driver) mapped to `ERR_INVALID_VEHICLE_STATE` / `ERR_INVALID_DRIVER_STATE`.

**Orchestrator truncation check (independent)**: 510 lines; tail ends at `| ERR_TRIP_NOT_CHARGED | 409 |`, a complete final table row of §5; `grep -c` confirms 56 endpoint rows and 52 error rows. Not truncated — no regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T02:35:00.000Z

Test generation for task_2483 is complete and verified.

## Files written

**Stage 1 — `test_helpers/` (9 files)**
- `__init__.py` — barrel export; importing the package registers the error→HTTP-status map
- `types.py` — 22 enums + 12 TypedDicts with PRD-exact field names
- `api_client.py` — `ApiClient(GenericApiClient)` with 56 endpoint methods + module-level `api_client`
- `api_errors.py` — `ApiErrorId` (51 ids), `HTTP_STATUS_CODES`, `set_error_http_status_map` registration (string keys)
- `constants.py` — PRD thresholds + `TEST_DEFAULTS` (RBM zone geometry, fares, caps, block window)
- `factories.py` — 12 payload factories
- `test_users.py` — fixed-role identities, header constants, `make_rider_headers` / `make_driver_headers` / `headers_without_identity`
- `assertions.py` — versioned-entity / ledger-shape / state / instant-normalising assertions
- `fixtures.py` (936 lines) — ~70 plain builders, 17 composite scenario builders, 18 `@pytest.fixture` wrappers; every one builds state from scratch through PRD endpoints (per-test DB reset)

**Stage 2 — `test_suite/` (13 files)**
- `conftest.py` — explicit fixture re-exports + `client` and six role-header fixtures
- `test_01_fare_settlement_depth.py` (9), `test_02_subsidy_reporting_depth.py` (12), `test_03_matching_and_manifest_depth.py` (12), `test_04_block_lifecycle_and_gates_depth.py` (12), `test_05_scheduling_conflicts_depth.py` (13)
- `test_06_resource_shapes.py` (22), `test_07_state_machine_guards.py` (20), `test_08_pricing_and_metrics.py` (16), `test_09_validation_rules_intake.py` (18), `test_10_validation_rules_operations.py` (10), `test_11_endpoint_and_error_surface.py` (13), `test_12_access_control_and_concurrency.py` (8)

## Test counts per queue

- **Queue A (Difficulty, §1.8)** — 58 tests across `test_01`–`test_05`, covering all 25 instances / 9 rules (0 stubs in the difficulty index)
- **Queue B (Corner, §1.9)** — 107 tests across `test_06`–`test_12`, covering 55 of 56 non-stub instances; the 31 `excluded_because:` stubs were not translated
- **Total: 165 tagged tests, 183 collected items** (`pytest --collect-only` → "183 tests collected in 0.47s", no import errors)

## Coverage audit

- Unknown tags: none. Stub tags used: none. All 31 `excluded_because:` cross-references resolve.
- Difficulty: every one of the 25 instances has ≥2 tests.
- Corner: every one of the 55 translated instances has ≥1 test; the single `MISS` is the deliberate skip below.
- Structural: exactly one `Design:` line per test and always the docstring's last line; a `PRD:` citation in every docstring; no skip/xfail markers; no scaffold vocabulary.
- Citations: **165/165 PRD quotes verbatim** against `workspace/PRD.md` (whitespace-normalised substring check).

## Instances skipped

**`Corner/state_machines/board_side_effects_stamp_pickup_and_increment_block_boardings`** — fails the unique-derivability condition. The instance asserts `VehicleBlock.boardings_count == 1` immediately after `POST /pool-assignments/{id}/board`, but PRD §3.6 places `boardings_count increases by seats_held` in the **completion** hop and §3.8 states "`boardings_count` only grows when a ride completes". A PRD-only implementer uniquely derives 0 at boarding time, so the asserted outcome is not PRD-derivable. Skipped outright — no placeholder, no marker.

## Notable yaml-vs-PRD literal conflicts (PRD won; tests assert the PRD value)

- `baseline_direct_minutes` is computed at intake (asserted 6 and 12, not null) in two instances.
- `boardings_count == 1`, not 2, while a block is OPEN.
- `applied_cap` is null at quote time.
- The yaml's error-priority numbering (12/52, 20/28, 30/58) differs from PRD §2.9's (11/32, 15/20), but the winning error ids are identical.
- Zone create takes ten client inputs, not eleven.
- The "no POST/PATCH/DELETE under /fare-transactions" claim is unspecified by the PRD, so immutability is asserted via field shape instead.
- Cross-zone paired stop resolves to `ERR_PAIRED_STOP_INVALID` by §2.9 ordering.

Nothing under `workspace/implementation/` was read or created, by me or by any of the 12 Stage 2 subagents (the constraint was restated verbatim in every brief).

## Step 6: Generate implementation — 2026-09-03T02:20:00.000Z

Implementation complete and boot-verified.

## Files written

`workspace/implementation/` — 26 files, no seeded data, no persistence:

- **Launcher** — `start.sh` (pip-installs only when `import flask` fails, then `exec python3 app.py`; honours `$PORT`, default 10000), `requirements.txt` (`Flask>=3.0`)
- **Core** — `app.py` (factory + `ApiError`/`HTTPException`/catch-all handlers), `db.py` (12 in-memory dict stores, `base_record`, per-request-idempotent `touch`), `clock.py` (logical clock, default exactly `2026-08-01T00:00:00Z`), `errors.py` (51-id catalog with statuses), `response.py` (envelope + `has_more`), `validation.py`, `middleware.py` (6 roles, entity-backed Rider/DriverUser identity, ownership helpers), `calculations.py` (all Decimal arithmetic: fare ladder, match score, corridor geometry, fleet sizing, subsidy), `serializers.py`, `listing.py`
- **Routes** — `routes/{zones,stops,fleet,forecasts,blocks,trips,assignments,reports}.py`
- **Services** — `services/{blocks,metrics,fares,offers,cascades,reports}.py`

## Endpoints

**56 implemented**, matching the scaffold exactly: service-zones 5, virtual-stops 5, transit-connections 3, vehicles 4, drivers 4, riders 3, demand-forecasts 3, vehicle-blocks 6, trip-requests 6, pool-assignments 6, fare-transactions 2, subsidy-reports 7, plus `POST /_clock/set_current_utc`. The 35-step rejection ladder from PRD §2.9 is applied in priority order at every write endpoint.

## Verification

- `python3 -m py_compile` clean on all 18 modules.
- Fresh `start.sh` boot on a free port: `GET /service-zones` → 200 with a well-formed empty array envelope (`total_count: 0`, `has_more: false` — confirming no seeded data), unauthenticated request → 401 `ERR_UNAUTHENTICATED`. Server killed afterwards; no processes or ports left held, `__pycache__` removed.
- Two black-box smoke rounds (33 + 48 assertions) passed 100%. Round 1 covered the full happy path zone → stops → fleet → forecast → block → trip → match → accept → board → complete → close → subsidy certify, with hand-checked derived values (baseline 15, match_score 8, fare 275, `actual_revenue_hours` 1.42, `boardings_per_revenue_hour` 1.41, base/surge blocks 2/2, `subsidy_per_trip_cents` 12846). Round 2 covered manual dispatch with OCC (`ERR_STALE_VEHICLE_BLOCK_VERSION` 412 vs. success on the current version), `ERR_DRIVER_REST_BUFFER`, `ERR_CURB_CAPACITY_EXCEEDED`, `ERR_TRANSFER_WINDOW_MISSED`, the decline → requeue → attempt-exhaustion → 3-strike driver suspension cascade, settlement with `applied_cap: DAILY` (ledger CHARGE 350 + CAP_REBATE −50, rider counter 300), refund and double-refund `ERR_TRIP_NOT_CHARGED`, the zone-suspend sweep plus `ERR_ZONE_NOT_ACTIVE` intake block, and pagination/`limit=0` → 422.

Nothing under `test_suite/` or `test_helpers/` was read or written.

Note (orchestrator): Steps 5 and 6 were launched concurrently in a single assistant message, giving the impl generator physical isolation from `test_suite/` (which did not exist when it started).

## Step 7: Run tests and iterate — 2026-09-03T03:05:00.000Z

All 8 parallel rounds pass at 183/183. Exiting with the summary.

## Summary

**Iterations run:** 2 (each an 8-round parallel stability sweep, `setsid`-detached, no early exit).

**Tests deleted:** none. All four failing tests survived STEP 1 — each cites a verbatim PRD sentence (§3.7 step 5 transfer-credit clamp, §3.5 manual-dispatch null `match_score`, §3.6 decline first-hop capacity give-back, §3.5 frozen `seats_held`/`wav_positions_held`) and each is uniquely derivable from it.

**Fixes applied to `test_helpers/`:** one, and it was the sole defect in the whole artifact.
- `test_helpers/fixtures.py`, `setup_dispatch_ready()` — the builder passed the operator-assigned code positionally *and* splatted the override bag, so any caller supplying `rider_code` / `vehicle_code` / `driver_code` in `*_overrides` crashed the fixture with `TypeError: create_rider() got multiple values for argument 'rider_code'` before a single HTTP request was issued. The codes are now lifted out of the override dicts with `.pop(..., default)`, which honours the caller's override instead of colliding with it. This made the override path PRD-faithful rather than weakening anything.

**Fixes applied to `implementation/`:** none. No implementation defect was found; the four failures were a single upstream fixture bug masquerading as four independent ones (the TRIAGE HINT pattern — all four shared the identical setup error, and all four traced to one `test_helpers` line).

**Final round-by-round figures (quoted from `results.${i}.json`):** rounds 1–8 all 183 / 183, `failed: 0`, `errors: 0`, `skipped: 0`. Iteration 1 was a clean, fully deterministic 179/183 in every round (same 4 tests, same `TypeError`) — no flakiness surfaced anywhere across the 16 rounds, so no load-induced or timing-sensitive failure needed to be distinguished from a real defect.

**Orchestrator independent verification**: all 8 `results.{1..8}.json` present on disk (each ~57.6 KB, mtime 02:45), re-parsed with `json.load` → every round `passed=183 total=183 failed=0 errors=0 skipped=0`. Sweep artifacts confirmed, not merely reported.

**Orchestrator Step 8 decision**: Step 7 applied 1 `test_helpers/` fix and 0 `implementation/` fixes, with 0 deletions and 0 `test_suite/` fixes. The documented skip condition requires zero fixes across *all four* categories, so it is not met — but the single fix was a pure Python-signature bug in a fixture builder (`TypeError` before any HTTP request), which reveals no PRD silence and no PRD/implementation mismatch. Step 8 is therefore run for form's sake with that item as the sole `<step_7_diff>` entry; the expected and correct outcome is a near-zero diff. Step 9's full scan is where residual ambiguity actually gets closed.

## Step 8: Finalize PRD — 2026-09-03T03:12:00.000Z

`PRD_FINALIZED.md` created as a verbatim copy — **zero edits**, which is the correct outcome for this Step 7 diff.

## Line counts
- `PRD.md`: 510 lines
- `PRD_FINALIZED.md`: 510 lines
- Delta: **0 lines / 0.00%** (identical md5 `fd9aee824816dda36ef6bb5b2b88b3f4`)

## Changes
None. No `{section} — {insert|revise}` bullets, because no Step 7 diff item revealed PRD silence or PRD/impl mismatch.

## Verification of the single diff item
The sole fix was in `test_helpers/fixtures.py` `setup_dispatch_ready()` (lines ~555-563): the operator-assigned codes are now lifted with `.pop("vehicle_code", "V1")` etc. instead of being passed positionally *and* splatted. Confirmed present and confirmed to be a pure Python-signature defect that raised before any HTTP request — it cannot encode any PRD claim.

Each of the four PRD sentences the surviving tests cite was then verified against `implementation/`; all four match the PRD verbatim, so none needed pinning:

1. **§3.7 step 5 transfer-credit clamp** — `calculations.py:170-173`: `min(connection["transfer_credit_cents"], category_cents)` when waived, else `0`. Exactly PRD's "smaller of the connection's `transfer_credit_cents` and the post-multiplier fare from step 4".
2. **§3.5 manual-dispatch null `match_score`** — `routes/assignments.py:120` passes `None` as the score into the shared `offers.create_offer(...)`, which stores it verbatim at `services/offers.py:125`. Automatic matching passes the real winning score (`services/offers.py:97,103`).
3. **§3.6 decline first-hop capacity give-back** — `routes/assignments.py:171-175` flips the assignment to `DECLINED` then calls `block_service.recompute_block`, which at `services/blocks.py:50-70` re-derives `seats_committed`/`wav_positions_committed` as sums of `seats_held`/`wav_positions_held` over `OFFERED|ACCEPTED|ONBOARD` and re-derives the envelope. Because `party_size >= 1`, `changed` is always true on a decline, so `db.touch(block)` always advances `version` — matching PRD's "the block's `version` advances by 1".
4. **§3.5 frozen `seats_held` / `wav_positions_held`** — a repo-wide grep finds these keys written only at `services/offers.py:120-121` (creation) and read at `services/blocks.py:50,51,57` and `serializers.py:73`. No mutation path exists anywhere, so they are frozen as PRD requires.

## Per-edit pre-edit search log
Not applicable — no edits were committed. The enumeration above is the same global consistency search that would have preceded any candidate edit; it terminated in "no edit needed" for all four subjects.

One nearby impl detail deliberately NOT encoded, as outside the Step 7 diff scope: `recompute_block` also re-derives `boardings_count` as the sum of `seats_held` over `COMPLETED` assignments, and its `db.touch` is conditional on an actual value change. Both consistent with PRD prose as written; neither exercised nor fixed by Step 7. (Flagged here for Step 9's full scan.)

## Step 9: Complete PRD — 2026-09-03T03:28:00.000Z

**Files:** `PRD_FINALIZED.md` 510 lines / 95,137 chars → `PRD_COMPLETED.md` 512 lines / 103,409 chars (**+2 lines, +8,272 chars**, 33 changed hunks, no sections added, one new in-section paragraph in §2.5).

**Counts:** 28 ambiguity-pins, 8 mismatch-revisions (36 total).

### Changes

- §2.2 — insert — ambiguity — `api_request_timestamp` is the one timestamp read from real wall-clock rather than the logical clock — `response.py:_timestamp`
- §2.3 — insert — ambiguity — `limit`/`offset`: empty string takes the default; non-integer literal and out-of-range are both shape violations — `validation.py`
- §2.3 — insert — ambiguity — `created_at` ascending ties break on insertion order (oldest first) — `db.py` (`sort_key`)
- §2.3 — revise — ambiguity — filters are exact string equality except the three boolean filters (`true`/`false`/`1`/`0`); empty value ignored, unmatched value yields an empty page not a rejection — `listing.py`, `validation.py`
- §2.4 — insert — ambiguity — a recompute writing back identical values does not refresh `updated_at`; a `seq_pickup`-only renumber doesn't either — `services/blocks.py:31-74`
- §2.4 — insert — ambiguity — `version` advances by exactly 1 per request regardless of mutation count — `db.py` (`touch`)
- §2.5 — revise — ambiguity — all domain timestamps read the logical clock; the envelope timestamp is the sole exception — `clock.py`, `response.py`
- §2.5 — insert (new in-section paragraph) — ambiguity — pins per-field rendering: `created_at`/`updated_at` always 3 fractional digits; body-supplied instants echoed verbatim; clock-stamped domain fields stored as the clock's raw string; `promised_dropoff_utc` via `fmt_like` — `clock.py`
- §2.5 — insert — ambiguity — clock endpoint returns a single-field object `current_utc`, echoed exactly as spelled — `routes/zones.py`
- §2.6 — insert — ambiguity — `seats_committed`/`wav_positions_committed` are always re-derived from the active manifest, never nudged incrementally — `services/blocks.py:56-74`
- §2.7 — revise — ambiguity — half up means half **away from zero**; fixed-place quantities travel as JSON numbers so trailing zeros are not preserved — `calculations.py` (`rhu_int`)
- §2.7 — insert — ambiguity — the negative-subsidy case: −1.5 cents settles at −2 — `calculations.py:subsidy_per_trip_cents`
- §2.9 step 7 — insert — ambiguity — body parsed as JSON regardless of `Content-Type`; absent/empty body = `{}`; explicit `null` = omitted; optional `note`/`reason` may be `""`, mandatory ones may not — `validation.py` (`get_body`, `opt_*`)
- §2.9 step 11 — insert — ambiguity — on manual dispatch the trip's state is examined before the block's, so `ERR_INVALID_TRIP_STATE` wins — `routes/assignments.py:66-69`
- §2.9 step 15 — **revise** — **mismatch** — virtual-stop create removed from the `ERR_ZONE_MISMATCH` list; its cross-zone pairing is caught earlier as `ERR_PAIRED_STOP_INVALID` — `routes/stops.py`
- §2.10 — insert — ambiguity — every `created_at` ascending cascade order breaks ties on insertion order; trip-cancel releases and forecast supersessions added to the ordered list — `db.py:by_created_at`, `routes/forecasts.py`
- §2.10 — insert — ambiguity — `version` moves at most once per request, and a recompute that changes nothing is not a mutation (block, zone scorecard, rider fare counters) — `db.py:touch`, `services/blocks.py:74`, `services/metrics.py:67-70`, `services/fares.py:35-40`
- §2.11 — **revise** — **mismatch** — cross-zone pairing on stop create reports `ERR_PAIRED_STOP_INVALID`, not `ERR_ZONE_MISMATCH` — `routes/stops.py`
- §3.1 — insert — ambiguity — a zone-suspension sweep leaves `projected_detour_minutes`/promised times as they stood; only `unserved_trip_count` can move in the follow-on scorecard recompute — `services/cascades.py`, `services/metrics.py`
- §3.1 — **revise** — **mismatch** — `stop_code` uniqueness is operator convention, not server-enforced; `zone_code` is the only enforced code — `routes/stops.py`
- §3.1 — insert — ambiguity — a `paired_stop_id` resolving to nothing is `ERR_VIRTUAL_STOP_NOT_FOUND`; self-pairing is structurally impossible — `routes/stops.py`
- §3.2 — **revise** — **mismatch** — `vehicle_code` uniqueness unenforced — `routes/fleet.py`
- §3.2 — **revise** — **mismatch** — `driver_code` uniqueness unenforced — `routes/fleet.py`
- §3.2 — **revise** — **mismatch** — `rider_code` uniqueness unenforced — `routes/fleet.py`
- §3.4 — **revise** — **mismatch** — the fleet-sizing ceiling is evaluated against *every* overlapping published forecast, and an open exceeding any one of them is rejected — `services/blocks.py:121-155`
- §3.4 — insert — ambiguity — on close only `boardings_per_revenue_hour` can move; the zone's `version` advances only when it does, the block's always — `services/blocks.py`, `services/metrics.py:67-70`
- §3.4 — insert — ambiguity — block cancel leaves `boardings_count` untouched: it stays the sum of `seats_held` over `COMPLETED` assignments — `services/blocks.py:56-74`
- §3.5 — insert — ambiguity — on an exact tie the requested pickup instant wins, carrying its own string through unchanged — `services/offers.py:22-29`
- §3.5 — insert — ambiguity — `seq_pickup` is re-derived across the whole active manifest on every manifest change; a sibling renumber is not a mutation of that sibling — `services/blocks.py:31-45`
- §3.5 — **revise** — **mismatch** — trip cancel reverts a `fare_status` of `QUOTED` **or `CAPPED`** to `UNPRICED` — `services/fares.py:139-143` (`void_quote`)
- §3.6 — insert — ambiguity — accept with the decline streak already at 0 does not mutate the driver row — `routes/assignments.py:149-151`
- §3.6 — insert — ambiguity — complete re-derives `boardings_count` as the sum of `seats_held` over `COMPLETED` assignments — `services/blocks.py:56-74`
- §3.7 — insert — ambiguity — the provisional quote writes the step-7 capped charge (not the step-6 net), leaves `applied_cap` null, appends no ledger row, and runs only when the fare axis is actually `UNPRICED` — `services/fares.py:69`, `services/offers.py:110-145`
- §3.7 — insert — ambiguity — a refund's ledger row repeats the trip's `applied_cap`, and counters are re-summed against the rider's *stored* anchors so a cross-date refund leaves the daily counter untouched — `services/fares.py:127-143`
- §3.9 — insert — ambiguity — both block and trip scopes are confined to the report's own `zone_id` — `services/reports.py:block_scope`/`trip_scope`
- §5 — revise — ambiguity — `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405) and `ERR_INTERNAL` (500) sit outside the domain catalogue as transport-level failures — `app.py:28-33`

**Verified leads:** both confirmed. `recompute_block` derives `boardings_count` from `COMPLETED` assignments (pinned in §3.4 cancel and §3.6 complete), and its `db.touch` is `changed`-guarded (generalized in §2.4/§2.10 after finding the same guard in `metrics.recompute_zone` and `fares.recompute_rider_counters`, plus `recompute_seq_pickup` which never touches siblings at all).

**No §4 edits needed:** the 56 impl routes were mechanically diffed against the 56 PRD table rows (identical), and each endpoint's `@endpoint([...])` role set matched the Authorized Role(s) column.

**Orchestrator integrity check**: `PRD_COMPLETED.md` = 512 lines / 103,409 chars; tail ends at `| ERR_TRIP_NOT_CHARGED | 409 |`, a complete final §5 row; 56 endpoint rows, 52 error rows, 28 headings retained. Not truncated.

## Pipeline complete — 2026-09-03T03:30:00.000Z

All nine steps done. Final state: SCAFFOLD.yaml + both design indices; `workspace/PRD.md` (510 lines), `workspace/PRD_FINALIZED.md` (510, verbatim copy — Step 8 correctly made zero edits), `workspace/PRD_COMPLETED.md` (512, 36 pins/revisions); `test_helpers/` (9 files) + `test_suite/` (13 files, 183 collected tests); `workspace/implementation/` (26 files, Python + Flask, in-memory only, no seeded data) passing 183/183 in all 8 rounds of the final stability sweep, with `results.{1..8}.json` on disk as evidence.
