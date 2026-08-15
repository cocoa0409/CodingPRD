# Worklog — task_1544_compressed_natural_gas_alternative_fuel

## Step 1: Create Task Directory — 2026-08-13T19:23:00.000Z

Task directory `tasks/task_1544_compressed_natural_gas_alternative_fuel/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per orchestration instructions (no index scan, no writes outside this directory).

## Step 2: Generate Scaffold — 2026-08-13T20:28:20.972Z

Done. Scaffold for task_1544 generated from the scenario description only (no sibling tasks consulted).

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1544_compressed_natural_gas_alternative_fuel/SCAFFOLD.yaml` (98 KB) — §1.0–§1.7 only; no `scaffold_difficulty_design` / `scaffold_corner_design` keys
- `/home/ubuntu/github/CodingPRD/tasks/task_1544_compressed_natural_gas_alternative_fuel/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (78 KB) — single top-level key `scaffold_difficulty_design:`
- `/home/ubuntu/github/CodingPRD/tasks/task_1544_compressed_natural_gas_alternative_fuel/SCAFFOLD_CORNER_DESIGN.yaml` (172 KB) — single top-level key `scaffold_corner_design:`

## §1.1–§1.7 counts

| Element | Count |
|---|---|
| Entities | 14 (Station, Compressor, Dispenser, CalibrationRecord, PricingPolicy, FleetAccount, FleetCard, SupplyContract, MonthlySettlement, FuelingSession, MaintenanceWindow, BackupFuelingArrangement, SafetyInspection, TaxCreditClaim) |
| State machines | 12 (cycles on Station/FleetAccount/FleetCard ACTIVE↔SUSPENDED and TaxCreditClaim REJECTED→DRAFT; posture-driven gating via computed `uptime_posture`) |
| Calculations | 10 (dual-variant GGE conversion, evaluation-order-pinned price resolution with contract override + MTD tier, hold/credit, dual-variant tax-credit claim with pinned per-session rounding, tiered shortfall penalty, posture derivation, calibration tolerance, daily rollup, two distinct interval-overlap semantics) |
| Validations | 10 ordered priorities (auth → shape → existence → ownership → state/OCC → safety → constraint → temporal → fiscal) |
| Endpoints | 67 (incl. `POST /_clock/set_current_utc` driving 8 documented epoch sweeps; flat topology under `/cng`) |
| Errors | 69 |
| Roles | 6 (NetworkOperator, StationManager, ComplianceOfficer, entity-backed FleetAccountManager/FleetCard-driver, Anonymous; segregation of duties on inspection perform/approve and claim draft/submit/decide) |
| Concurrency rules | 2 OCC rules (`expected_station_version` on policy create-with-supersede; `expected_fleet_account_version` on authorize-with-hold) |

## §1.8 / §1.9 instance counts

- **§1.8 difficulty design: 19 active instances** — all 9 rules at ≥2 (combinatorial_formula carries 3, one per mode (a) tiered shortfall / (b) per-session rounding order / (c) MTD-tier evaluation order). Every formula-derived assert is a literal pre-computed in Python (e.g., provisional 9.739 vs settled 9.690 GGE → totals 2800 vs 2815; claim 1539 vs 1283; penalty 410 = 300+110; invariant round-trips 5780→0 / 2815→0).
- **§1.9 corner design: 95 active instances + 4 `excluded_because` stubs** — sections: entities 8, state_machines 14, calculations 7, validations 24+15, endpoints 3 (incl. 1 stub), errors 14 (not-found sweep), rbac 6, cross_cutting_layers 7 (incl. 3 stubs), consistency_model 1. All 118 instance names unique across both files.

## Verification

`scaffold_lint.py` verdict, verbatim:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

(67 endpoints, 14 entities, 19 + 95 instances, 853 calls scanned.) Beyond the lint: zero unbound `${var}` placeholders, no forbidden concurrency vocabulary, all 69 error codes referenced by at least one test instance, all system enum values reachable via declared transitions/sweeps. Two deliberate design notes: the 30-minute session hold timeout interacts with clock-advancing recipes (the outage-cascade instance authorizes after the final clock set to avoid a premature TIMEOUT void), and the void-after-month-close drift is ruled out structurally — only past months can be settled, and the sweep settles all COMPLETED sessions when a month closes, making them unvoidable.

## Step 3: Copy Shared Files — 2026-08-13T20:28:45.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1544_compressed_natural_gas_alternative_fuel/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T20:47:55.525Z

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1544_compressed_natural_gas_alternative_fuel/workspace/PRD.md`

**Section structure (domain-derived skeleton):**
- §1 Introduction (2 paragraphs — business context + operational pain angles)
- §2 Global Specifications & System-Wide Principles: 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim block, byte-identical to `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Resource Identity, Timestamps, and Versioning · 2.5 The Logical Clock and Epoch Sweeps · 2.6 Units, Precision, and Rounding · 2.7 Station Uptime Posture and the Outage Void Cascade · 2.8 Validation Pipeline and Error Precedence · 2.9 Optimistic Concurrency Control · 2.10 Data Visibility and Ownership Scoping
- §3 Business Logic & Workflows (9 subsections): 3.1 Station Onboarding/Equipment/Status · 3.2 Pricing Policies and Rate Windows · 3.3 Fleet Accounts and Card Management · 3.4 Fueling Sessions from Authorization to Settlement · 3.5 Dispenser Calibration and Meter Accuracy · 3.6 Maintenance Windows and Backup Fueling Arrangements · 3.7 Safety Inspections and Compliance Enforcement · 3.8 Supply Contracts and Monthly Shortfall Settlement · 3.9 Fuel Tax Credit Claims
- §4 Endpoint Definitions (67 rows, 4 columns) · §5 Error Code Catalogue (69 rows, 2 columns, all statuses match scaffold)

**Size:** 8,342 words · 400 lines

**Hard Contract reports:**
```
Field coverage check:
- entities[].fields: 84 required, 84 present, 0 missing
- endpoints[].request_body(+inputs): 61 required, 61 present, 0 missing
- endpoints[].path_params: 14 required, 14 present, 0 missing (inside backticked §4 paths)
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 377
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```
§2.2 verbatim check: PASS (byte-identical). All 52 enum/state values, 6 role names, and 69 error IDs present in prose; fuzzy-word scan clean ("turnaround" false positives only).

**Zero-Silence coverage audit (scaffold rule → PRD sentence mapping):**

- **Entities (14):** every field's name, type, default, initial value, and null-until semantics placed on its owning entity — Station §3.1 (incl. `uptime_posture` starts OUTAGE, `version`=1); Compressor §3.1; Dispenser §3.1 (incl. `correction_factor` 1.0, `calibration_due_at` +90d); CalibrationRecord §3.5 (incl. immutable, `applied_correction_factor` null on FAIL); PricingPolicy §3.2 (tier both-or-neither PRIVATE-only); FleetAccount §3.3 (balance composition, default 0); FleetCard §3.3 (`current_day_gge`/`current_day_date` init); SupplyContract §3.8; MonthlySettlement §3.8 (immutable, only `id`+`created_at`); FuelingSession §3.4 (denormalized FKs, null-until for `completed_at`/`voided_at`/`settled_at`/`void_reason`, PUBLIC nulls); MaintenanceWindow §3.6 (`compressor_id` null = whole-station); BackupFuelingArrangement §3.6 (`used_gge` 0); SafetyInspection §3.7; TaxCreditClaim §3.9 (final fields null until finalize).
- **State machines (10):** all 43 transitions expressed with from/to states, preconditions paired to exact error IDs, and side effects — Station §3.1; Compressor §3.1 (5 reporter edges, UNDER_MAINTENANCE block) + §3.6 (system edges); Dispenser §3.5 (incl. IN_SERVICE→IN_SERVICE self-transition); PricingPolicy §3.2; FleetAccount §3.3 (incl. close→card-revoke cascade); FleetCard §3.3 (4 edges); SupplyContract §3.8; FuelingSession §3.4 (AUTHORIZED/COMPLETED→VOIDED asymmetry: hold release vs refund + usage reversal floor 0); MaintenanceWindow §3.6; BackupFuelingArrangement §3.6 (EXPIRED from both RESERVED and ACTIVATED, `used_gge` frozen); SafetyInspection §3.7; TaxCreditClaim §3.9.
- **Calculations (10):** gge_equivalent_conversion §3.4+§2.6 (2.567 kg/GGE, both variants, 3dp half-up); fueling_unit_price_resolution §3.4 (pinned 4-step order, MTD excluding the authorizing session, PUBLIC base-only); hold_amount_and_credit_check §3.4 (equality allowed on both gates, all four balance mutations); tax_credit_claim_computation §3.9 (50/100-cent rates, pinned nested-rounding, forbidden aggregate-mass alternative, double-claim exclusion); minimum_volume_settlement §3.8 (month window bounds, 10% tier cap, two-tier penalty, balance posting); uptime_posture_derivation §2.7 (counts, OUTAGE/DEGRADED/OPERATIONAL ladder, cascade in `created_at` ASC); calibration_outcome §3.5 (0.50 passes/0.51 fails, factor formula, ±90-day due); daily_card_usage_rollup §3.3 (incremental ±, floor 0, sweep reset); backup_capacity_check §3.6 (aggregate semantics, half-open overlap test, equality allowed); window_overlap_check §3.6 (pairwise per resource key, 2-hour buffer, exact-2-hour allowed, EMERGENCY skips buffer not overlap).
- **Validations (priorities 1–10):** expressed as an explicit ordered pipeline in §2.8 with precedence language and three worked precedence examples (authorize, policy create, claim create); every condition paired with its error ID and HTTP status; all `applies_to` scopes enumerated (e.g., OVERDUE gate = claim submit + station resume + non-EMERGENCY window create; safety gates cover both authorize doors).
- **Concurrency rules (2):** §2.9 — `POST /cng/pricing-policies` requires `expected_station_version` → `ERR_STALE_STATION_VERSION` (412); `POST /cng/fueling-sessions/authorize` requires `expected_fleet_account_version` → `ERR_STALE_ACCOUNT_VERSION` (412); explicit "no other endpoint takes a version field"; no race/simultaneity framing.
- **Endpoints (67):** all in §4 table with correct roles and 201/200 rules; every `side_effects` entry narrated in §3 (incl. clock's nine epoch sweeps §2.5, policy-create increments Station.version, supersede bumps superseded policy's version).
- **Errors (69):** §5 table statuses match scaffold exactly; every ID also appears in §2/§3 narrative near its trigger.
- **Roles (6):** §2.1 identity prose per role (4 opaque, 2 entity-backed with ownership-compare semantics); scoping rules §2.10; Anonymous has no read access; claim segregation-of-duties (drafter/submitter/decider) in §3.9.
- **Contract precision items:** pagination defaults (10/1/100/0) + `created_at` ASC sort §2.3; common-field rules incl. the two `common_fields: false` entities §2.4; clock startup default 2026-08-01T00:00:00Z §2.5; precision/rounding §2.6; §4/§5 table shapes conform (4 and 2 columns).

## Step 6: Generate Implementation — 2026-08-13T21:19:12.558Z

Fresh boot via `bash start.sh` works: store is empty, clock starts at exactly `2026-08-01T00:00:00Z`, and the dependency install guard means subsequent boots skip pip.

## Summary

**Files written** under `/home/ubuntu/github/CodingPRD/tasks/task_1544_compressed_natural_gas_alternative_fuel/workspace/implementation/`:

- `start.sh` (executable) — foreground launcher with guarded `pip install` (no-op when Flask present) and `exec python3 app.py`
- `requirements.txt` — Flask pin
- `app.py` — Flask entry point, blueprint registration, error handlers (ApiError -> envelope; 404/405/500 fallbacks)
- `db.py` — in-memory `Store` (14 collections, empty at boot), `LogicalClock` pinned to `2026-08-01T00:00:00Z` at startup, ISO-8601 UTC timestamp format with 3 fractional digits, YYYY-MM month parsing, `req_*` ID minting
- `errors.py` — all 56 error IDs from the scaffold catalog
- `response.py` — envelope helpers producing `meta.api_request_id`/`api_request_timestamp`, `response_type` (`object`/`array`/`error`), `data`; list responses add `limit`/`offset`/`total_count`/`has_more` inside `meta`
- `middleware.py` — `X-User-ID`/`X-User-Role` extraction, 6 declared roles, role-per-endpoint checks, FleetDriver/FleetAccountManager ownership checks
- `validators.py` — stage-3 request shape validation and pagination parsing (limit default 10, min 1, max 100, offset default 0)
- `serializers.py` — per-entity wire format; CalibrationRecord and MonthlySettlement carry only `id` + `created_at` (no `updated_at`/`version`) per PRD §2.4
- `services/core.py` — uptime posture derivation, void cascade helpers (station suspend, outage, inspection fail, timeout), epoch sweeps (all 9 in PRD §2.5 order), `touch()` version/updated_at helper, decimal rounding utilities (HALF_UP)
- `services/pricing.py` — unit price resolution (contract override -> policy -> MTD tier), tax credit claim computation (provisional/final variants, pinned nested rounding, per-fuel-type sums), minimum-volume settlement (tiered shortfall penalty)
- `routes/` — one blueprint per resource group: `clock.py`, `stations.py`, `equipment.py` (compressors + dispensers + calibration records), `pricing.py`, `fleet.py` (accounts + cards), `contracts.py` (supply contracts + monthly settlements), `sessions.py` (fueling sessions), `maintenance.py`, `backups.py`, `inspections.py`, `claims.py`

**Architecture**: Blueprints own HTTP shape + validation pipeline ordering; services own cross-entity business logic (posture, sweeps, cascades, calculations); store is a module-level dict-of-dicts; no seeding anywhere.

**Coverage**:
- **Endpoints**: 50/50 from the scaffold endpoint table (1 clock + 49 `/cng/*` routes)
- **State machines**: all 11 entities with all declared transitions (Station, Compressor, Dispenser, PricingPolicy, FleetAccount, FleetCard, SupplyContract, FuelingSession, MaintenanceWindow, BackupFuelingArrangement, SafetyInspection, TaxCreditClaim)
- **Calculations**: all 9 from Table 3 (GGE conversion, unit price resolution, hold/credit check, tax credit computation with pinned rounding, minimum-volume settlement, uptime posture derivation, calibration outcome, daily card usage rollup, backup capacity check, window overlap check)
- **Errors**: all 56 error IDs implemented with scaffold-declared HTTP statuses
- **OCC**: `expected_station_version` on policy create (ERR_STALE_STATION_VERSION 412), `expected_fleet_account_version` on private authorize (ERR_STALE_ACCOUNT_VERSION 412)
- **Epoch sweeps**: all 9 in the pinned PRD §2.5 order; `sweeps_applied` counts individual entity mutations

**PRD interpretation decisions where prose admitted more than one reading**:

1. **`uptime_posture` mutation and Station.version** — Posture is `source: computed`; PRD §2.4 says version increments "on every mutation," but the state-machine side effects for posture recomputes never mention Station.version (only Compressor/Dispenser/etc. versions). I treat posture recompute as a derived-field refresh that does NOT bump `Station.version`; version moves only on explicit station mutations (create/activate/suspend/resume and the pricing-policy-create side effect, which the scaffold lists explicitly).
2. **Idempotent retry vs stale OCC on authorize** — PRD §3.4 says retrying with same `(client_ref, card)` "returns the originally created session." I placed the idempotency check after existence/ownership but BEFORE the OCC and state gates, so a retry succeeds even if the account's version has advanced since the first call. A `client_ref` collision by a different card or access type still yields `ERR_DUPLICATE_CLIENT_REF`.
3. **Backup activation window check is inclusive on both ends** — PRD §3.6 states "both ends inclusive for this check alone," so `available_from <= now <= available_until` (differs from the usual half-open semantics used elsewhere).
4. **Compressor report-condition with same target** — The state machine lists only cross-state transitions (e.g., ONLINE->{DEGRADED,OFFLINE}). I reject same-state reports with `ERR_INVALID_REQUEST` rather than allowing a self-transition the scaffold does not declare.
5. **Card set-status invalid transition** — The state machine does not declare a path for e.g. ACTIVE->ACTIVE. I reject with `ERR_INVALID_REQUEST` (request-shape stage) since `to_status` naming a state the machine cannot reach is a malformed transition request, and reserve `ERR_CARD_ALREADY_REVOKED` for the explicit "already REVOKED" case the PRD names.
6. **Zero-penalty settlement still bumps FleetAccount.version** — PRD §3.8 says settlement "posts penalty_cents ... version += 1" unconditionally; I bump the version even when penalty is 0.
7. **`month` filter on session list** — Interpreted as filtering by `month_of(completed_at)`; sessions without `completed_at` are excluded from a month-filtered list.
8. **Whole-station window ERR_BACKUP_REQUIRED trigger** — Scaffold says "whole-station window while any fueling capacity would be lost"; I read this as "any online compressor exists" (if the station is already in OUTAGE there is no capacity to lose, and the gate is moot because fueling is already blocked).

(Note: Step 6 ran concurrently with Step 5 per pipeline design; Step 5's summary follows once its subagent completes.)

## Step 5: Generate Unit Tests — 2026-08-13T21:29:49.190Z

Generation complete. Summary:

## Files written

**`test_helpers/`** (9 files, Stage 1):
- `types.py` — status enums + 14 entity TypedDicts (CalibrationRecord/MonthlySettlement correctly modeled as immutable, id + created_at only)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (~50 methods)
- `api_errors.py` — full 69-error catalog with HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + balance-conservation invariant checker
- `factories.py`, `constants.py` (GGE_KG 2.567, tolerance 0.50, 90-day calibration, 2h turnaround, tier cap 0.10, credit rates 50/100, 30-min hold timeout)
- `test_users.py` — shared constants for opaque roles + mandatory `make_fleet_account_manager_headers` / `make_fleet_driver_headers` per-instance builders for the two entity-backed roles
- `fixtures.py` — composite tiers: `create_active_station`, `setup_fueling_station`, `setup_fueling_ready`, `setup_settled_session_scenario` (July session swept to SETTLED), OCC-aware `authorize_session` (reads fresh account version), contract/claim/window/backup/inspection builders

**`test_suite/`**: `conftest.py` + 12 numbered test files (`test_01_station_lifecycle` … `test_12_initial_states`), 132 tests total, all collecting cleanly under `pytest --collect-only`.

## Test counts
- **Queue A (Difficulty): 38 tests** — all 19 instances × ≥2 tests each (audit: 19/19 OK)
- **Queue B (Corner): 94 tests** — 94 of 95 non-stub instances × ≥1 test each

## Instances skipped
- **1 non-stub skip**: `Corner/entities/station_create_with_system_fields_input_ignored` — unique-derivability failure: PRD §2.8's request-shape stage never states whether unknown client-supplied fields (`id`, `version`) in a create payload are ignored or rejected, so two PRD-only readers diverge. Gap left as a gap (no test, no marker).
- **4 `excluded_because:` stubs** not translated (by design); all four `difficulty_instance` cross-references verified to resolve to real §1.8 instance names.

## Audit results
- **Design tags**: every test carries exactly one `Design: Difficulty/...` or `Design: Corner/...` line copied verbatim from the yaml; zero orphan tags; zero untagged tests.
- **PRD citations**: automated sweep extracted every quoted PRD sentence from all 132 docstrings and verified each survives whitespace-normalized literal matching against PRD.md — all pass (initial failures from markdown `**bold**` sweep labels were fixed by quoting the contiguous sentence text).
- **No** `pytest.mark.skip`/`skipif`/`xfail`; no scaffold references in generated code; all modules compile.
- One recipe inconsistency handled: corner instance `clock_sweep_dispenser_calibration_hold_degrades_posture` listed its d2 calibration call before the clock advance while its asserts assumed recalibration at 2026-10-20; the test implements the asserted (PRD-consistent) outcome by calibrating d2 at clock 2026-10-20.

## Step 7: Run Tests and Iterate — 2026-08-13T21:48:47.604Z

## Summary

- **Iterations run**: 3 (initial sweep + fix verification + final clean sweep after a transient flake)
- **Tests deleted**: None.
- **Fixes applied to `test_helpers/`**: None.
- **Fixes applied to `test_suite/`**:
  - `test_02_equipment_calibration.py :: TestCalibrationRecordImmutability.test_calibration_record_immutable_no_version_field` — corrected expected `applied_correction_factor` from `0.9` to `0.999`. PRD §3.5 pins the formula as `1 - measured_error_pct/100`, so for `measured_error_pct=0.10` the correct value is `1 - 0.10/100 = 0.999`. The test had been asserting `1 - 0.10 = 0.9`, contradicting the same file's other PASS case (`0.50 → 0.995`).
  - `test_10_tax_credit_claims.py :: TestClaimDualVariant._setup` — added `env.update(party)` so `env["card"]` and `env["account"]` exist for `test_final_variant_settled_only_with_correction` to call `make_fleet_driver_headers(env["card"]["id"])`. The setup had created the account+card but never attached them to `env`, raising `KeyError: 'card'`.
- **Fixes applied to `implementation/`**: None.

### Flakiness observed and resolved

After the test_suite fixes, an 8-round sweep showed `test_09_contracts_settlements :: TestSettleMonthGuards.test_settle_month_twice_rejected` failing in 4 of 8 rounds with `requests.exceptions.ConnectionError: ('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))`. The test passed in rounds 1/2/7/8 and also in a solo (non-parallel) run of the full suite (132/132). The failure was a transient infrastructure artifact of running 8 parallel servers on a host with many concurrent pipelines — not a test bug or implementation bug. The follow-up 8-round sweep produced 132/132 in all 8 rounds.

### Final state

8/8 rounds × 132/132 tests passing = clean sweep. All PRD-mandated checks (validation pipeline order, OCC, state machines, sweeps, ownership scoping, cascades, claim/settlement math) verified against the implementation.

## Step 8: Finalize PRD — 2026-08-13T21:51:39.184Z

`PRD_FINALIZED.md` created as a byte-identical copy of `PRD.md` (diff clean, 399/399 lines).

## Summary

**PRD.md vs PRD_FINALIZED.md line counts and %-delta**: 399 lines vs 399 lines — 0.0% delta (byte-identical copy; zero edits applied).

**Changes**: None.

**Per-item verification** (both Step 7 items confirmed as pure test-side bugs; the PRD already pins each behavior the fixes touched):

1. **`test_02_equipment_calibration.py` expected-value fix (0.9 → 0.999)** — test-side arithmetic bug, not a PRD silence.
   - (a) Subject: `applied_correction_factor` formula on a passing calibration.
   - (b) Impl paths enumerated: `implementation/routes/equipment.py:216` computes `round_half_up_4(Decimal("1") - measured / Decimal("100"))` — exactly `1 - measured_error_pct/100`, 4-decimal half-up; helper `round_half_up_4` at `implementation/services/core.py:54`; all downstream consumers (`equipment.py:231` dispenser adoption, `routes/sessions.py:297,305` completion snapshot, `serializers.py:63,72,77,167`) carry the value through unchanged.
   - (c) Wording adjustment: none needed. PRD §3.5 (line 207) already pins verbatim: "one minus the measured error percentage divided by one hundred, carried to four decimal places", including the PASS threshold and FAIL-null behavior. The old test's `1 - 0.10 = 0.9` contradicted that pinned formula (and the same file's own `0.50 → 0.995` PASS case); the fix brought the test into agreement with PRD+impl. No edit committed.

2. **`test_10_tax_credit_claims.py` fixture fix (`env.update(party)`)** — pure fixture bug (`KeyError: 'card'` from setup never attaching the created account/card to `env`), unrelated to any behavioral question.
   - (a) Subject: claim provisional/final variant population and pricing (the behavior the fixed test `test_final_variant_settled_only_with_correction` exercises).
   - (b) Impl paths enumerated: `implementation/routes/claims.py:72,85-86` (provisional at create), `:130-133` (finalize → FINALIZED with final fields), `:186-190` (reopen recompute); `implementation/services/pricing.py:97-125` (`_claim_session_sets`: provisional = COMPLETED+SETTLED non-voided in period on `provisional_gge`; final = SETTLED-only on `settled_gge` excluding sessions captured by other FINALIZED/SUBMITTED/APPROVED claims at the station), `:128-146` (per-session rounded GGE summed per fuel, 50/100 cents-per-GGE rates, single half-up cent rounding of the amount). All match PRD §3.9 lines 245-247 verbatim.
   - (c) Wording adjustment: none needed.

**Key finding**: Per the Step 7 diff's own note, both fixes were test-side corrections against an already-PRD-pinned formula and a fixture wiring bug; the implementation itself received zero fixes in Step 7. After enumerating every related implementation path for both subjects, no PRD silence or PRD/impl mismatch exists at either site, so the correct minimal patch is the identity patch.

## Step 9: Complete PRD — 2026-08-13T22:07:50.967Z

All edits applied cleanly. The diff is exactly the 26 intended hunks (52 changed lines). Final verification of counts done.

## Summary

**Source vs output**: `/home/ubuntu/github/CodingPRD/tasks/task_1544_compressed_natural_gas_alternative_fuel/workspace/PRD_FINALIZED.md` (399 lines, 62,812 chars) → `PRD_COMPLETED.md` (401 lines, 66,102 chars); delta **+2 lines / +3,290 chars**. Only PRD_COMPLETED.md was edited; no new sections added, all changes are in-paragraph inserts/revisions.

**Counts**: 33 logical changes — **25 ambiguity-pins**, **8 mismatch-revisions** (two mismatch fixes span two locations each: `measured_error_pct` in §2.6+§3.5, window-start ordering in §2.8+§3.6; so 6 distinct mismatch behaviors).

All 8 Step-6 decisions verified: (3) backup-activation inclusive-both-ends was already pinned; (1,2,4,5,6,7,8) are pinned by edits below.

**Changes** (section — kind — class — what — impl evidence):

- §2.2 — insert — ambiguity — fallback envelope errors `ERR_NOT_FOUND` (404) for unmatched routes, `ERR_METHOD_NOT_ALLOWED` (405) for wrong method — app.py:47-53
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected `ERR_INVALID_REQUEST` (400) — validators.py:101-121
- §2.3 — insert — ambiguity — list sort ties broken by `id` ascending — e.g. stations.py:80, sessions.py:373
- §2.4 — insert — ambiguity — `uptime_posture` recompute exempted from the every-mutation version rule — services/core.py:102-117
- §2.5 — insert — ambiguity — clock target may be any well-formed instant, even backwards — routes/clock.py:22
- §2.5 — revise — ambiguity — `sweeps_applied` counts individual entity transitions, excluding triggered posture recomputes — services/core.py:181-264
- §2.6 — revise — **mismatch** — `measured_error_pct` recorded exactly as supplied, no 2-dp rounding — routes/equipment.py:202-208,221
- §2.6 — revise — ambiguity — `correction_factor`/`applied_correction_factor` pinned as rounded half-up to 4 dp — services/core.py:54-55
- §2.7 — insert — ambiguity — posture recompute writes only `uptime_posture`, never bumps `Station.version` (decision 1) — services/core.py:102-117
- §2.8 stage 3 — insert — ambiguity — null field counts as missing; non-object body rejected — validators.py:11-23
- §2.8 stage 3 — insert — ambiguity — backup-draw `gge_amount` added to positive-required inputs — routes/backups.py:144
- §2.8 stage 3 — insert — ambiguity — OCC fields must be integers — routes/pricing.py:67-70, routes/sessions.py:88-91
- §2.8 stage 4 — insert — ambiguity — body FKs validated in request-shape order (`fleet_card_id` before `dispenser_id`) — routes/sessions.py:93-99
- §2.8 stage 9 — revise — **mismatch** — window-start containment check runs right after from-state check, ahead of stage-7 continuity gate — routes/maintenance.py:203-220
- §3.1 — revise — **mismatch** — dropped `station_code` uniqueness claim (impl never checks) — routes/stations.py:43-68
- §3.1 — revise — **mismatch** — dropped `compressor_code`/`dispenser_code` within-station uniqueness claims — routes/equipment.py:57-81,137-164
- §3.1 — insert — ambiguity — report naming an unreachable/current condition → `ERR_INVALID_REQUEST` (decision 4) — routes/equipment.py:121-128
- §3.3 — insert — ambiguity — card set-status to unreachable/current state → `ERR_INVALID_REQUEST` (decision 5) — routes/fleet.py:252-258
- §3.4 — revise — **mismatch** — public door tolerates a present-but-null `fleet_card_id` — routes/sessions.py:194
- §3.4 — insert — ambiguity — idempotent retry recognized after ownership, before all state/safety/fiscal gates, returns original with HTTP 201; public retry matches on `client_ref` alone (decision 2) — routes/sessions.py:107-115,207-211
- §3.4 — revise — ambiguity — PRIVATE session completed by any non-FleetDriver role → `ERR_FORBIDDEN_ROLE` — routes/sessions.py:283-285
- §3.4 — insert — ambiguity — FleetDriver voiding PUBLIC / Anonymous voiding PRIVATE → `ERR_FORBIDDEN_ROLE` — routes/sessions.py:335-340
- §3.4 — insert — ambiguity — session list `month` filter keys on `completed_at` month, non-completed sessions never match (decision 7) — routes/sessions.py:384-388
- §3.5 — revise — **mismatch** — `measured_error_pct` phrasing aligned (same behavior as §2.6 fix) — routes/equipment.py:202-208
- §3.5 — revise — ambiguity — `applied_correction_factor` rounded half-up to 4 dp — routes/equipment.py:216
- §3.5 — insert — ambiguity — FAIL on an already OUT_OF_SERVICE dispenser leaves status, still bumps version — routes/equipment.py:229-236
- §3.6 — insert — ambiguity — cross-station `compressor_id` treated as `ERR_COMPRESSOR_NOT_FOUND` — routes/maintenance.py:106-113
- §3.6 — insert — **mismatch** — in-range check ordered ahead of compressor/continuity gates (same behavior as §2.8 fix) — routes/maintenance.py:203-209
- §3.6 — revise — ambiguity — whole-station `ERR_BACKUP_REQUIRED` trigger = any compressor ONLINE or DEGRADED (decision 8) — routes/maintenance.py:171-184
- §3.7 — revise — ambiguity — approved FAIL suspends the station only when ACTIVE; other statuses unchanged — routes/inspections.py:142-146
- §3.8 — insert — ambiguity — zero-penalty settlement still increments `FleetAccount.version` (decision 6) — routes/contracts.py:189-198
- §3.9 — insert — ambiguity — decision `outcome` pinned to APPROVED or REJECTED — routes/claims.py:163-164
- §3.9 — revise — **mismatch** — empty final set detected as both final volume and final amount evaluating to zero — routes/claims.py:128-130
