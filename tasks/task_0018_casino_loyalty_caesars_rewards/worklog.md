# Worklog — task_0018_casino_loyalty_caesars_rewards

## Step 1: Create task directory — 2026-05-27T00:00:00Z

Skipped NNNN auto-allocation per user instruction. Task directory `./tasks/task_0018_casino_loyalty_caesars_rewards/` was pre-created with empty `workspace/`. No bash mkdir needed.

## Step 2: Generate scaffold — 2026-05-27T12:21:00Z

All three files generated and pass `scaffold_lint.py` with `VERDICT: clean lint`.

---

## Summary

Generated three scaffold artifacts for `task_0018_casino_loyalty_caesars_rewards`:

**Files:**
- `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0018_casino_loyalty_caesars_rewards/SCAFFOLD.yaml`
- `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0018_casino_loyalty_caesars_rewards/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0018_casino_loyalty_caesars_rewards/SCAFFOLD_CORNER_DESIGN.yaml`

**Complexity profile:**
- Primary archetype: `pricing_engine`; secondary: `compliance_audit`
- Layers: dual_variant_calculation, rate_threshold_triggers, optimistic_concurrency, scheduled_deferred_actions
- entity_topology: flat; state_machine_shape: parallel (Member has 3 independent dimensions); role_model: segregation_of_duties

**§1.1–§1.7 counts (SCAFFOLD.yaml):**
- entities: 9 (Member, Property, Host, GamingSession, CompRoomBooking, SelfExclusion, HostAssignment, VelocityAlert, AnnualResetRun)
- state_machines: 7 (Member×3 parallel dimensions + CompRoomBooking + HostAssignment + AnnualResetRun + SelfExclusion)
- concurrency_rules: 2 (both OCC on Member.version, one for host-assignment create, one for comp-booking create)
- calculations: 3 (tier_credit_accrual, comp_room_rate with PROVISIONAL/FINAL variants, velocity_monitor)
- validations: 20 priority-ordered rules
- endpoints: 40 (38 business + 1 GET reverse-reachability sub-resource + 1 `/_clock/set_current_utc` test-driving)
- errors: 20
- roles: 4 (Member entity_backed; MemberServices/LoyaltyManager/ComplianceOfficer opaque)

**§1.8 SCAFFOLD_DIFFICULTY_DESIGN.yaml:**
- 9 rules × 2 instances each = 18 total instances
- All 9 Difficulty Rules from §0.5 covered (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant)

**§1.9 SCAFFOLD_CORNER_DESIGN.yaml:**
- 9 sections walked (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model)
- 34 total instances: 30 with full test_recipes + 4 `excluded_because:` stubs pointing to §1.8 coverage

**Lint verdict:** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (282 calls scanned across 18+30 instances; 11 initial FK_REVERSE_UNREACHABLE issues resolved by setting `api_prefix: ""` and adding `assigned_host_id?` to `GET /members`.)

## Step 3: Copy INSTRUCTION.md — 2026-05-27T12:21:30Z

Copied `./INSTRUCTION.md` → `tasks/task_0018_casino_loyalty_caesars_rewards/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-27T12:26:00Z

All 20 error IDs present. PRD is 261 lines.

---

**Summary**

**Output**: `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0018_casino_loyalty_caesars_rewards/workspace/PRD.md` — 261 lines.

**Section list**:
- §1. Introduction (2 paragraphs)
- §2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control
  - 2.2 API Response Structure (verbatim block)
  - 2.3 Pagination
  - 2.4 Common Resource Properties
  - 2.5 Optimistic Concurrency Control
  - 2.6 Hierarchical Consistency and Cascades
  - 2.7 Numerical Precision and Rounding
  - 2.8 Universal Loyalty and Property Independence
  - 2.9 Segregation of Duties on Host Engagements
  - 2.10 Validation Order
  - 2.11 Test-Driving the Clock
- §3. Business Logic & Workflows (9 subsections)
  - 3.1 Member Onboarding and the Three Parallel State Dimensions
  - 3.2 Property and Host Setup
  - 3.3 Recording Gaming Sessions and the Tier-Credit Accrual Engine
  - 3.4 Velocity Monitoring
  - 3.5 Host Assignments and the Two-Person Approval Discipline
  - 3.6 Comp-Room Bookings and the Provisional / Final Rate
  - 3.7 Self-Exclusion and the Two-Level Cascade
  - 3.8 The Annual Reset
  - 3.9 State Transition Reference
- §4. Endpoint Definitions (4-column table)
- §5. Error Code Catalogue (2-column table)

**Scattering notes**:
- §3 grouping = mixed entity-lifecycle + cross-cutting (velocity, self-exclusion cascade, annual reset separated as concerns). §3.9 anchors all state-pair disambiguation back to §4.
- `expected_member_version` is named both in §2.5 (precise contract) and re-stated in §3.5 / §3.6 narrative.
- Velocity thresholds embedded in business prose with dollar conversions ("greater than or equal to one and a half million cents (fifteen thousand US dollars)").
- Tier thresholds (15000 / 75000 / 150000) embedded in §3.3 promotion narrative.
- Discount fractions (0.10/0.40/0.70/1.00) and market multipliers (1.20/1.00/1.10) rendered in §3.6 as natural-language English fractions, no operators or fuzzy words.
- Per-step round-half-up cents and per-session round-half-up TC rounding kept distinct (§2.7 + §3.3 + §3.6).
- 365-day exclusion period kept in business safety context (§3.7); single-session loss cap rendered as "one hundred million cents — the regulatory single-session reporting cap of one million US dollars".

**Hard Contract Reports**:

```
Field coverage check:
- entities[].fields: 42 required, 42 present, 0 missing
- endpoints[].request_body: 22 required, 22 present, 0 missing
- endpoints[].query_params: 14 required, 14 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 20 checked, 20 expressed in prose (§2.10 enumerates all in priority order), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_member_version + ERR_STALE_MEMBER_VERSION + HTTP 412 named in §2.5, restated in §3.5 / §3.6), 0 missing
- state_machines[].transitions: 27 checked, 27 fully expressed (§3.3–§3.8 narrative + §3.9 state-pair index), 0 missing
- calculations[]: 3 checked, 3 fully expressed (tier_credit_accrual in §3.3, comp_room_rate PROVISIONAL/FINAL in §3.6, velocity_monitor in §3.4), 0 missing
- validations[] conditions: 20 checked, 20 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all endpoint side-effects described in §3 workflow narrative; all applies_to scopes enumerated in §2.10 and §3, 0 missing
- entities[].fields[] structured content: 42 checked, defaults / enums / types / initial values reconstructible from prose, 0 missing
- sibling-branch symmetry: tier ladder (4 transitions promotion + 3 demotion to GOLD), velocity (3 forward transitions), booking cancel (PENDING and CONFIRMED branches), host-assignment terminal branches — all rendered with equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 378
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Zero-Silence audit notes**:
- `SelfExclusion` and `VelocityAlert` explicitly called out in §2.4 as carrying only `id` and `created_at` (no `updated_at`, no `version`) — common_fields:false handled.
- All three OCC-bearing endpoints (host-assignment create, comp-room-booking create, clear-velocity) explicitly say they take `expected_member_version`; `clear-velocity` rule covered in §3.4.
- `Property.occupancy_cap=20` scaffold constant embedded narratively in §3.6 ("the property's occupancy cap of twenty") even though the field is implicit (not in entity fields list).
- AnnualResetRun lifetime-invariant (`tier_credits_lifetime_invariant_before_cents` / `_after_cents`) and the `members_reset_count` counter all named and explained in §3.8.

## Step 5: Generate unit tests — 2026-05-27T12:55:00Z

All deliverables in place. Here's the summary report:

---

## Summary

**Stage 1 — `test_helpers/` (9 files, ~1,740 lines)**

- `types.py` — entity TypedDicts (Member, Property, Host, GamingSession, CompRoomBooking, HostAssignment, AnnualResetRun carry full common fields; SelfExclusion and VelocityAlert carry only `id`+`created_at` per PRD §2.4) and status/role enums.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (~35 methods incl. clock control).
- `api_errors.py` — `ApiErrorId` enum (21 errors incl. `ERR_INVALID_REQUEST`) + HTTP status map registered with the framework via `set_error_http_status_map`.
- `assertions.py` — `_assert_common_full` / `_assert_common_append_only` branching; `assert_member/property/host/gaming_session/comp_room_booking/host_assignment/self_exclusion/velocity_alert/annual_reset_run`, plus the `assert_lifetime_invariant_preserved` domain invariant.
- `factories.py` — payload factories for the 8 input-bearing entities.
- `constants.py` — tier thresholds (15000/75000/150000), tier mults, market mults, velocity thresholds (500k/1.5M), session cap, 365-day exclusion, occupancy cap = 20.
- `test_users.py` — opaque MS/LM/CO headers plus `make_member_headers(member_id)` for the entity-backed Member role (and named alice/bob LM constants for SOD tests).
- `fixtures.py` (~780 lines) — clock + single-entity creates + tier promotion helpers + booking lifecycle helpers + Tier-3 composite bootstraps (gold/platinum/diamond member, pending/confirmed/completed booking, two-manager HA, ACTIVE HA, cascade setup, OCC twin-hosts, cyclic exclusion, due-reset variants, **n-overlapping-bookings** loop for the 20+1 occupancy test).
- `__init__.py` — barrel export.

**Stage 2 — `test_suite/` (17 files, 1 conftest + 16 test files, 66 tests, ~2,675 lines)**

Difficulty queue (queue A) — 9 rules × 2 instances × 2 tests = **36 tests**:
- `test_01` dual_variant (2+2), `test_02` combinatorial (2+2), `test_03` non-linear SM (2+2), `test_04` cascades (2+2), `test_05` priority pairs (2+2), `test_06` boundary precision (2+2), `test_07` cross-entity (2+2), `test_08` temporal overlap (2+2), `test_09` compensating invariants (2+2).

Corner queue (queue B) — **30 tests** for 30 non-stub instances (4 stubs correctly NOT translated: `host_assignment_self_approve_blocked_by_sod`, `velocity_monitor_threshold_500000_already_covered`, `priority_state_versus_safety_already_covered`, `cascade_self_exclusion_already_covered` — all have valid `difficulty_instance` cross-references):
- `test_10` entity CRUD (6), `test_11` SM corners (5), `test_12` calc corners (3), `test_13` validations (3), `test_14` endpoints (2), `test_15` errors+RBAC (6), `test_16` cross-cutting+consistency (5).

**Coverage audit (final)**

- Difficulty: 18/18 instances × ≥2 tests = 36 tests. No shortfalls, no extras.
- Corner: 30/30 non-stub instances × ≥1 test = 30 tests. No shortfalls, no extras, no stub translated.
- Total: **66 tests**, every test carries exactly one `Design: …` line resolving verbatim to a real instance.
- Verbatim PRD-citation check: **72 quoted PRD fragments across all docstrings, 0 fails** against the PRD (modulo whitespace + backticks/asterisks + ellipsis breaks).

**Instances skipped: none.** Every design instance survived the two-condition filter.

**Audit notes**

- `Difficulty/cross_entity_state_dependency/host_assignment_approve_requires_host_active`: the design recipe explicitly redirected to an SOD trigger because the scaffold lacks a host-deactivation endpoint. Both translated tests assert `ERR_SOD_VIOLATION` per the recipe's actual `assert` block; PRD §3.5 + §2.9 cover SOD verbatim.
- `Difficulty/priority_pair_validation_conflict/business_safety_vs_business_constraint_excluded_overrides_tier_eligibility`: only `ERR_MEMBER_EXCLUDED` is reachable on `POST /comp-room-bookings` (no tier check on create); the second test asserts the complementary `ERR_TIER_INELIGIBLE_FOR_COMP` on `/confirm` for a GOLD non-excluded member. Both error_ids are PRD-verbatim with their trigger conditions. The "priority 6 beats 11" claim cannot be observed in a single response, so it's exercised via the two complementary observations.
- `Corner/rbac/rbac_member_entity_backed_can_only_view_own_record`: PRD §2.1 mandates the ownership check on body-`member_id` vs `X-User-ID` but does not pin the rejection `error_id` (a PRD-only reader could reasonably choose `ERR_UNAUTHORIZED` or `ERR_NOT_FOUND`). Per the two-reader rule, this test uses `validate_error_is_one_of([ERR_UNAUTHORIZED, ERR_NOT_FOUND])` instead of a single-id assertion.
- `member_create_missing_email_returns_400` and `gaming_session_invalid_game_type_enum_rejected` assert only `status_code == 400` (no specific `error_id`) because PRD does not pin the missing-required-field or bad-enum error id.

## Step 6: Generate implementation — 2026-05-27T12:55:00Z

Implementation is complete. Here is the summary for worklog.md:

---

# Implementation Generation Summary — task_0018_casino_loyalty_caesars_rewards

## File List (24 files)

`workspace/implementation/`
- `start.sh` — bash launcher (executable, foreground, `exec python3 app.py`)
- `requirements.txt` — Flask==3.0.3
- `app.py` — Flask entry point, blueprint registration, error handlers, listens on `$PORT` (default 10000), binds `0.0.0.0`
- `auth.py` — `X-User-ID`/`X-User-Role` header extraction, 4-role allowlist (`Member`, `MemberServices`, `LoyaltyManager`, `ComplianceOfficer`)
- `clock.py` — process-local logical clock (`set_clock` / `now` / `parse_iso` / `iso`); resets on every boot
- `common.py` — id minting, payload validation, pagination (limit/offset, defaults 10/0, max 100), ROUND_HALF_UP helpers, `stamp_create` / `stamp_update` / `stamp_audit_create`
- `db.py` — in-memory dict stores; `reset()` for explicit clear; never seeded at boot
- `errors.py` — `ApiError` class + verbatim error-id constants from SCAFFOLD §1.6
- `response.py` — envelope `{meta, response_type, data}` with `api_request_id`/`api_request_timestamp` and pagination fields per PRD §2.2
- `services/calculations.py` — `tier_credit_accrual`, `comp_room_rate` (PROVISIONAL & FINAL share formula), `velocity_monitor`; all Decimal-based with `ROUND_HALF_UP`
- `services/cascades.py` — `cascade_on_exclusion` (revoke host assignments, cancel bookings, null `assigned_host_id`) and `cascade_on_velocity_suspended` (cancel pending/confirmed bookings)
- `services/serializers.py` — per-entity JSON views ordered by SCAFFOLD field order
- `routes/` — one blueprint per resource: `members`, `properties`, `hosts`, `host_assignments`, `gaming_sessions`, `comp_room_bookings`, `self_exclusions`, `velocity_alerts`, `annual_reset_runs`, plus `clock_route` for `POST /_clock/set_current_utc`

## Key Modules

- **App**: `app.py` registers 10 blueprints, installs `ApiError`/`404`/`405`/`HTTPException`/`Exception` handlers that all emit the standard error envelope. Reads `PORT` env var, binds `0.0.0.0`, `threaded=True`.
- **Models / data**: `db.py` — pure dict stores per entity; no preload; threading.RLock used as a coarse mutex in every write-path with `with db.lock:`.
- **Blueprints**: each route file enforces role allowlist via `auth.require_role(...)`, then validation in scaffold priority order (auth → existence → state → OCC → business gates → temporal → uniqueness → overlap → fiscal cap).
- **Calculations**:
  - `tier_credit_accrual`: `(loss_cents/100) * game_mult * tier_mult` rounded HALF_UP to 2 dp per session before summing into ytd/lifetime.
  - `comp_room_rate`: `round(base*(1-discount))` then `round(step_a*market_mult)` — Rule 2 mode b (round per multiplication, both to integer cents).
  - `velocity_monitor`: sums RECORDED sessions' `theoretical_loss_cents` for the member where `ended_at ∈ (window_end - 3600s, window_end]`; ≥1_500_000 → SUSPENDED, ≥500_000 → FLAGGED.

## OCC + Cascades + Parallel State Machines Wiring

- **OCC** on `Member.version` lives at 3 endpoints (`POST /host-assignments`, `POST /comp-room-bookings`, `POST /members/{id}/clear-velocity`). Each route reads `expected_member_version` from the body and checks `expected != member["version"]` immediately after existence/state, raising `ERR_STALE_MEMBER_VERSION` (HTTP 412) — exactly matching scaffold §1.2.1 and PRD §2.5. No other endpoint takes a version field.
- **Cascades** (PRD §2.6 / §3.7) are isolated in `services/cascades.py`:
  - `cascade_on_exclusion(member)` iterates `db.host_assignments` (REVOKE pending/active) and `db.comp_room_bookings` (CANCEL pending/confirmed); each child gets its own `stamp_update` (own `updated_at` and own `version+=1`); `member.assigned_host_id` is nulled iff any ACTIVE assignment was revoked.
  - `cascade_on_velocity_suspended(member)` cancels pending/confirmed bookings only; same per-child stamping rules.
  - The Member-level `stamp_update` happens once *after* the cascade in the calling route, so a single self-exclusion produces exactly one Member.version bump plus N child-version bumps.
- **Parallel state machines**: `tier_status`, `exclusion_status`, `velocity_status` are independent fields on the same Member row. `POST /gaming-sessions` drives accrual + tier promotion (monotonic upgrade through GOLD→PLATINUM→DIAMOND→SEVEN_STARS via the `promote_tier` helper) and, after the recorded session is stored, runs `velocity_monitor`; if a VelocityAlert is created, the velocity machine advances (NORMAL→FLAGGED, NORMAL/FLAGGED→SUSPENDED), and a SUSPENDED transition fires `cascade_on_velocity_suspended` before the second Member.version stamp. `exclusion_status` is driven only by `POST /self-exclusions` (and `/reinstate`). The annual reset only resets `tier_status` and `tier_credits_ytd` for non-excluded members; lifetime totals are preserved and the before/after invariant is exposed on the run row.

## start.sh / PORT / 0.0.0.0 / foreground

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m pip install -q -r requirements.txt
exec python3 app.py
```

- `cd "$(dirname "$0")"` makes the script path-independent.
- `pip install -q -r requirements.txt` is idempotent across re-launches.
- `exec python3 app.py` replaces the shell process so signals propagate cleanly to Flask (`per-test-server` isolation issues SIGTERM/SIGKILL between tests).
- `app.py` reads `int(os.environ.get("PORT", "10000"))` and calls `app.run(host="0.0.0.0", port=port, debug=False, threaded=True)` — foreground, listens on the supplied port, binds all interfaces.
- No persistent state: every boot starts with empty `db.*` dicts and unpinned `clock._clock_override`, so each per-test restart is clean.

## Step 7: Test-and-fix loop — 2026-05-27T13:20:00Z

All 8 rounds pass: 66/66 each. Clean sweep on the second iteration.

# Summary

- **Iterations run:** 2 (initial baseline = 18 failed / 66; after fixes = 0 failed / 66 across all 8 parallel rounds).

- **Root cause (one upstream fixture bug masquerading as 18 failures):** The promotion helpers and several inline test promotions used a single oversized `GamingSession` (e.g. 1,500,000 cents SLOTS at GOLD) to cross the PLATINUM tier-credit threshold. Per PRD §3.4, that exact amount also trips the velocity SUSPENDED threshold (`>= 1_500_000 cents in the rolling 60-min window`), leaving the freshly-promoted member with `velocity_status=SUSPENDED`. The very next step in each test (`POST /comp-room-bookings`) was then correctly rejected by the PRD-required SUSPENDED gate with `ERR_MEMBER_VELOCITY_SUSPENDED`. The implementation's velocity check was correct; the fixtures had violated a PRD precondition.

- **Tests deleted:** none.

- **Tests partially relaxed (STEP 1c / unique-derivability):**
  - `test_suite/test_09_compensating_invariants.py :: test_two_member_lifetime_sum_preserved_across_execute` — removed the two `... == 50000` numeric-value asserts on `tier_credits_lifetime_invariant_before_cents` / `..._after_cents`. PRD §3.8 prose says these capture "the sum of `tier_credits_lifetime`" (a TC value) while the field name carries the `_cents` suffix — units are not uniquely derivable. The verbatim-derivable invariant (before == after) and `members_reset_count == 2` are kept.

- **Fixes applied to `test_helpers/`:**
  - `fixtures.py :: promote_member_to_platinum` — replaced the single 1_500_000 cents SLOTS session with two 750_000-cent SLOTS sessions spaced 2 hours apart so each rolling 60-min window stays at FLAGGED (≤ 750k cents), never SUSPENDED.
  - `fixtures.py :: promote_member_to_diamond_from_platinum` — replaced the single 3_000_000 cents TABLE_GAMES session with three 1_200_000-cent TABLE_GAMES sessions spaced 2 hours apart.
  - `fixtures.py :: bootstrap_property_and_diamond_member` — rewrote inline 7_500_000-cent SLOTS session as a multi-session ladder (PLATINUM stage + DIAMOND stage) using the fixed helpers.
  - `fixtures.py :: bootstrap_due_annual_reset_with_two_platinum_members` — split the two 2_000_000 / 3_000_000 cents single sessions into 2 / 3 sessions of 1_000_000 cents each spaced > 1 h apart.
  - `fixtures.py :: _shift_iso_by_hours` — new internal helper.

- **Fixes applied to test files (same class of fixture bug, but inline rather than via helper):**
  - `test_suite/test_01_dual_variant_calculations.py` — both tests in `TestCompRoomRateProvisionalVsFinalAcrossTierCrossing` rewrote inline 1_500_000-cent SLOTS / 3_000_000-cent TABLE_GAMES promotions to call `promote_member_to_platinum` / `promote_member_to_diamond_from_platinum`.
  - `test_suite/test_02_combinatorial_formulas.py :: test_platinum_international_base_5557_rounds_per_step_to_3667` — switched inline 1_500_000-cent SLOTS to `promote_member_to_platinum`.
  - `test_suite/test_02_combinatorial_formulas.py :: test_diamond_vegas_strip_base_3333_per_step_rounding` — switched inline 7_500_000-cent SLOTS to the two-stage helper ladder.

- **Fixes applied to `implementation/`:** none. The implementation's velocity gate, OCC ordering, validation priority, and rate calculations were already PRD-faithful.

- **Final state:** 8/8 parallel rounds, 66/66 tests passed.

## Step 8: Finalize PRD — 2026-05-27T13:23:00Z

The diff shows a single targeted in-line revision to §3.8 that pins the unit choice for the lifetime invariant fields.

## Summary

**PRD.md vs PRD_FINALIZED.md**:
- PRD.md: 260 lines
- PRD_FINALIZED.md: 260 lines
- Lines changed: 1 line (line 176) — 0% line-count delta, single in-line revision adding ~225 characters of pin text within an existing paragraph.

**Change (1 bullet)**:
- §3.8 (Annual Reset) — revise — pinned the unit of `tier_credits_lifetime_invariant_before_cents` / `tier_credits_lifetime_invariant_after_cents` as integer cents (each member's `tier_credits_lifetime` Tier-Credit value multiplied by 100, cross-member sum rounded half-up to a whole integer), making the `_cents` suffix load-bearing rather than ambiguous with the prose phrase "sum of `tier_credits_lifetime`" — impl: `workspace/implementation/routes/annual_reset_runs.py:144-152` (`_sum_lifetime_cents`: `Decimal(str(m["tier_credits_lifetime"])) … * Decimal("100").quantize(Decimal("1"), rounding=ROUND_HALF_UP)`).

**Notes on other Step 7 items (no PRD patch needed)**:
- The PLATINUM/DIAMOND promotion fixture rewrites (`promote_member_to_platinum`, `promote_member_to_diamond_from_platinum`, `bootstrap_property_and_diamond_member`, `bootstrap_due_annual_reset_with_two_platinum_members`, `_shift_iso_by_hours`) and the inline-promotion fixes in `test_01` and `test_02` were pure test-helper / test-fixture bugs (PRD-precondition violations: single sessions that simultaneously crossed the PLATINUM tier-credit threshold and the velocity SUSPENDED threshold). The implementation's velocity gate, OCC ordering, validation priority, and rate-calculation behavior were already PRD-faithful per the Step 7 diff ("Fixes applied to `implementation/`: none"), so no PRD prose patch is required for them.
