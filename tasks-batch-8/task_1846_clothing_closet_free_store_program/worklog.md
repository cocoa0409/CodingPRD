# Worklog — task_1846_clothing_closet_free_store_program

## Step 1: Create Task Directory — 2026-08-14T20:07:00.000Z

Pre-existing per pipeline invocation: `tasks/task_1846_clothing_closet_free_store_program/` and `workspace/` already created. Verified present.

## Step 3: Copy Shared Files — 2026-08-14T20:08:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1846_clothing_closet_free_store_program/workspace/INSTRUCTION.md` (1424 bytes).

## Step 2: Generate Scaffold — 2026-08-14T20:42:00.000Z

All three artifacts are written and lint-clean. Summary follows.

### Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1846_clothing_closet_free_store_program/SCAFFOLD.yaml` (§1.0–§1.7 only)
- `/home/ubuntu/github/CodingPRD/tasks/task_1846_clothing_closet_free_store_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1846_clothing_closet_free_store_program/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

No sibling task directories were inspected; the design is derived only from the scenario text and the skill specification (plus the skill's own template/examples/lint script).

### Counts

| Metric | Count |
|---|---|
| Entities | 14 |
| State machines | 11 (incl. cyclic Item, VolunteerShift, Client) |
| Calculations | 11 |
| Validation rules (ordered priorities) | 36 |
| Endpoints | 63 (incl. `POST /closet/_clock/set_current_utc`, default `2026-08-01T00:00:00Z`) |
| Error catalog | 34 |
| Roles | 5 (ProgramAdmin opaque; VolunteerLead/Volunteer → Volunteer; Client → Client; ReferralPartner → ReferralPartner) |
| OCC concurrency rules | 2 (`client-profile-stale-version`, `zone-capacity-stale-version`) |
| §1.8 instances (non-stub) | 19 — all 9 rules ≥2; combinatorial_formula has 3 (modes a/b/c) |
| §1.9 instances (non-stub) | 50, plus 2 `excluded_because` stubs (both dangling-checked) |

Lint verdict (verbatim):

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(784 calls scanned; 0 violations. Forbidden-vocabulary sweep: no matches. Instance names unique across both design files: 71/71.)

### Notable design decisions

- **Archetype**: quota/allocation primary (per-visit allowance, category caps, rolling 30-day item cap, zone capacity, voucher quota, shift seats) with temporal-windowing secondary (14-day cooldown with inclusive `>=` boundary, drive windows with 7-day buffer, half-open shift overlap, rotation windows). Flat topology, cyclic state shape, segregation-of-duties role model, immediate consistency.
- **Dual variants on different domains**: recycling credit (per-item per-category provisional vs tiered actual-scale final — pinned 45¢ vs 64¢ on identical items) vs zone inventory turnover (current-basis 1.0000 vs average-basis 2.0000 on identical data).
- **Combinatorial modes**: (a) allowance = nested `min(HARD_VISIT_CAP, round_half_up(min(HOUSEHOLD_CAP, base)×tier) + voucher)`; (b) recycling provisional pinned per-item-round-then-sum (33 vs 34 trap); (c) voucher monthly quota carryover `quota(m)=base+f(quota(m-1))` with pinned chronological evaluation (13 then 11).
- **Segregation of duties**: batch closer ≠ sorter, pickup recorder ≠ sealer (both enforced on `X-User-ID`, with dedicated `ERR_SOD_*` errors), plus dense ownership scoping for Client/ReferralPartner/Volunteer self-service.
- **Race-prone edges resolved via OCC only** on Client/StorageZone PATCH; everything else was re-classified to state preconditions per §1.2.1's filter.
- **Selector determinism**: rotation phase-in (eligibility/rank `current_stock ASC`/tie-break zone `created_at ASC`/empty-pool → stay OFF_SEASON) and recycling sweep (created_at ASC, stop-at-first-overflow) never use ids for decisions.
- **Reserved-stock semantics**: `zone.current_stock` counts STOCKED+RESERVED (physical occupation); returns/quarantine-restock bypass capacity; DISTRIBUTED items keep `distributed_from_zone_id` so the turnover window identity `start = current + distributed − stocked` reconciles exactly.

## Step 4: Generate PRD — 2026-08-14T20:52:00.000Z

All 34 scaffold errors are present in §5 (my earlier "35" was a miscount of the YAML list). All checks pass. Task complete — summary below.

### Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1846_clothing_closet_free_store_program/workspace/PRD.md` — 330 lines.

**Section list**:
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 User and Role-Based Access Control · 2.2 API Response Structure (byte-identical to canonical source, verified) · 2.3 Pagination · 2.4 The Logical Clock and Lazy Status Advancement · 2.5 Common Resource Properties · 2.6 Request Validation Order and Nested Path Resolution · 2.7 Optimistic Concurrency Control · 2.8 Zone Occupancy, Posture, and Season Compatibility · 2.9 Weights, Credits, and Numeric Precision
- §3 Business Logic (9 subsections): 3.1 Client Registration/Eligibility/Discipline · 3.2 Shopping Visit: Check-in Through Checkout · 3.3 Distribution Lines, Limits, and Returns · 3.4 Referral Partners and the Voucher Program · 3.5 Donation Intake, Sorting, and Grading · 3.6 Stocking, Quarantine, and Storage Zones · 3.7 Volunteer Shifts and Signups · 3.8 Special Drives and Seasonal Rotation · 3.9 Textile Recycling and Impact Reporting
- §4 Endpoint Definitions (4-column table, all 63 endpoints)
- §5 Error Code Catalogue (2-column table, all 34 errors with correct HTTP statuses)

**Scaffold elements covered**: all 14 entities and every field; all 10 state machines with every transition's preconditions and side effects (including auto-transitions: batch IN_SORT→SORTED at declared count, shift OPEN↔LOCKED at capacity, lazy voucher/drive advancement); all 10 calculations in precise prose (allowance 8+2/member cap 16, HARDSHIP ×1.5 round-half-up, hard cap 24; 14-day inclusive cooldown; 3 visits/30d; 30-item rolling cap; COATS 2 / INTERVIEW_ATTIRE 1 caps; half-open 30d and 28d windows; zone posture with 0.8 NEAR_FULL ratio and inclusive FULL boundary; voucher quota carryover with anchor month, 5-carryover cap, pinned ascending evaluation; per-item provisional vs tiered final recycling credit with all category weights/rates and 100/500 kg tiers; both turnover bases with denominator-1 guards; sweep stop-no-skip; rotation phase-out-then-phase-in selector with stock-then-zone-age ranking); both OCC rules; all 36 validations with explicit per-endpoint evaluation order (check-in chain, line-add 4-limit order, stocking order, signup order, issuance order, seal/pickup SoD order) and a global cascade in §2.6; all 5 roles with identity translations; logical clock start at 2026-08-01T00:00:00Z.

**Hard Contract audit results**:

```
Field coverage check:
- entities[].fields: 78 required, 78 present, 0 missing
- endpoints[].request_body: 51 required, 51 present, 0 missing
- endpoints[].query_params: 16 required, 16 present, 0 missing
- endpoints[].path_params: 2 required, 2 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: per-endpoint orderings expressed (check-in, line-add, stocking, signup, issuance, close, seal, pickup, execute, zone PATCH) plus global cascade in §2.6, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write op + expected_client_version/expected_zone_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: all transitions across 10 machines fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed, 0 missing
- validations[] conditions: 36 checked, all matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: expressed in workflow narratives, 0 missing
- entities[].fields[] structured content: defaults/null-until semantics reconstructible, 0 missing
- sibling-branch symmetry: OPEN/LOCKED complete+cancel, UPCOMING/ACTIVE close, RESTOCK/REJECT release rendered with equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 490
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Zero-Silence self-audit**: No scaffold rule was left unrenderable. Two notes: (1) the `end_at` "(exclusive)" annotation on VolunteerShift was deliberately not restated as an exclusivity claim because the operative check-in rule is inclusive at both bounds (`start_at` on-or-after, `end_at` on-or-before, per the transition precondition); the creation constraint "end strictly after start" is stated; (2) during drafting I caught and fixed two validation-ordering inconsistencies (seal and pickup in §3.9) so their prose order matches the scaffold's priority cascade (state before empty-check; shape before state before SoD).

## Step 5: Generate Unit Tests — 2026-08-14T21:20:00.000Z

All done. Final summary:

### Generated output

**`test_helpers/`** (Stage 1, 9 files):
- `types.py` — 14 entity TypedDicts + status/role enums (all entities carry `common_fields: true`, so all four system fields included)
- `api_client.py` — 48 endpoint methods under `/closet`, subclassing `GenericApiClient`
- `api_errors.py` — all 35 error IDs with HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity asserters + `assert_zone_posture_invariants`
- `factories.py` — payload factories, input fields only, PRD-exact names
- `constants.py` — allowance/frequency/cap/posture/quota/weight/tier constants
- `test_users.py` — `TEST_USERS` + per-instance builders for all four entity-backed roles (`make_volunteer_headers`, `make_volunteer_lead_headers`, `make_client_headers`, `make_referral_partner_headers`) plus `make_program_admin_headers(user_id)` for the segregation-of-duties seal/pickup pair
- `fixtures.py` — composite chains: `setup_sorting_staff`, `open_batch_in_sort`, `grade_items`, `setup_stocked_items`, `setup_rejected_items`, `checkin_visit`/`add_lines`/`checkout_visit`, `issue_voucher`, `setup_swept_recycling_batch`, seal/pickup with distinct admin identities
- `__init__.py` — barrel export

**`test_suite/`** (Stage 2): `conftest.py` + 10 test files, **87 tests**, all collecting under pytest.

### Coverage

**Queue A (Difficulty): 38 tests — all 19 instances covered with exactly 2 tests each.** No skips; every instance's asserted rule has verbatim PRD prose coverage (§2.4, §2.7, §2.8, §3.1–§3.9) and unique derivability.

**Queue B (Corner): 49 tests covering 49 non-stub instances.** The 2 `excluded_because:` stubs (`state_machines/drive_line_after_close_not_active`, `cross_cutting_layers/quarantine_restock_reconciles_zone_stock`) were verified to resolve to real difficulty instances and were not translated.

**Per-file:** test_01 registration/RBAC/OCC-client 9 · test_02 zones/stocking/OCC-zone 10 · test_03 items/batches/quarantine 11 · test_04 check-in/allowance/quota 11 · test_05 lines/limits/checkout 10 · test_06 returns/voids 5 · test_07 vouchers 7 · test_08 shifts/signups 8 · test_09 drives/rotations 7 · test_10 recycling/reports 9.

### Skipped instance (1)

- **`Corner/rbac/volunteer_signup_ownership`** — fails unique derivability (condition 2). The instance asserts a Volunteer creating a signup for another volunteer must get `ERR_FORBIDDEN`, but PRD §3.7 ownership-scopes only cancellation and check-in ("Cancellation and check-in are ownership-scoped: a `Volunteer` may cancel or check in only their own signup"), and nothing pins signup *creation* to the caller's own id; a PRD-faithful implementer could allow it. Gap left as a gap.

**Assertion-level relaxation (not a skip):** initial-`version == 1` literals (in the creation-defaults and both OCC instances) were replaced by "version increments by one" assertions, because PRD §2.5 pins the increment but never the initial value — a 0-based implementation would be PRD-consistent.

### Audit results

- Every test docstring ends with exactly one `Design:` line resolving to a real instance (machine-checked; no unknown tags, no dual/untagged tests)
- 120/120 docstring PRD quotes survive literal whitespace-normalized grep of `PRD.md` (C1/C2/C3)
- No `pytest.mark.skip`/`skipif`/`xfail`; no scaffold references in comments/docstrings; pyflakes clean; `pytest --collect-only` reports 87 tests

## Step 6: Generate Implementation — 2026-08-14T21:22:00.000Z

Implementation complete and verified. Summary follows.

### File list (`workspace/implementation/`)

- `start.sh` — foreground launcher, `exec python3 app.py`, guarded dependency install (`if ! python3 -c "import flask"`), binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask only
- `app.py` — Flask entry point, error handlers (envelope for `ApiError`/404/405/500), blueprint registration, per-request global RLock
- `db.py` — in-memory store (empty on boot, no seeding), logical clock starting at `2026-08-01T00:00:00Z`, `stamp_new`/`touch` helpers (id, created_at, updated_at, version, `_seq` insertion counter)
- `errors.py`, `response.py`, `middleware.py`, `util.py` — `ApiError`; envelope helpers (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`, pagination fields `limit/offset/total_count/has_more`); `X-User-ID`/`X-User-Role` auth with the five scaffold roles; ISO-8601 (3-fractional-digit, `Z`) parse/format, Decimal round-half-up helpers, field/pagination validators
- `services.py` — constants, lazy voucher/drive advancement, all calculations, serializers with computed fields
- `routes/` — 15 modules: clock, clients, visits, lines, donations, items, zones, rotations, volunteers, shifts, partners, vouchers, drives, recycling, reports

**Endpoint count: 63** — every row of the scaffold §1.5 table.

### Calculation implementations

- **visit_item_allowance** — `min(16, 8 + 2·max(0, hh−1))`; HARDSHIP → `round_half_up(base × 1.5)` (Decimal); voucher bonus added then `min(24, …)`; `voucher_bonus_applied` = voucher's `bonus_items` (0 without voucher). Drive pools accounted separately at line-add.
- **visit_frequency_gate** — second-precision truncation on both instants; inclusive 14-day boundary (`now >= last + 14d`); `waives_frequency` overrides cooldown only; `visits_in_30d < 3` never waived.
- **visit_window_stats** — half-open `(now−30d, now]`; checkout exactly 30d ago excluded; items counted only from `DISTRIBUTED` lines on in-window visits (returns stop counting automatically).
- **rolling_item_cap** — `items_in_30d + ACTIVE lines on visit + 1 > 30` → reject.
- **category_line_cap** — COATS 2 / INTERVIEW_ATTIRE 1, general lines only; drive lines exempt.
- **zone_posture** — FULL when `current_stock >= capacity` (inclusive); NEAR_FULL at `ceil(0.8·capacity)` via integer math `(8·cap+9)//10` to avoid float 0.8; else AVAILABLE.
- **voucher_quota_carryover** — months walked ascending from `activated_month_key` (`quota=base` at anchor), `carryover = min(5, max(0, quota(m−1) − issued(m−1)))`; issuance iff `issued(current) < quota(current)`.
- **recycling_credit** — provisional: per-item `round_half_up(est_weight × category_rate)` then sum; final: single tier rate on actual weight (<100 → 40, [100,500) → 44, ≥500 → 50; inclusive upward), one round-half-up on the total. All Decimal; weights 2dp.
- **recycling_sweep_assignment** — REJECTED unassigned candidates in creation order; stop (no skip-ahead) at the first item that would exceed `capacity_kg`.
- **seasonal_rotation_moves** — phase-out of STOCKED non-target/non-ALL_SEASON items with per-item zone cascade; phase-in of matching OFF_SEASON items oldest-first into eligible (season_policy ∈ {target, ALL_SEASON}, posture ≠ FULL) zones ranked by `current_stock` ASC then zone creation ASC; empty pool leaves item OFF_SEASON without error.
- **inventory_turnover** — 28d half-open window; `stock_at_window_start = current + distributed − stocked`; current-basis `wd / max(1, current_stock)`; average-basis `wd / max(1, round_half_up((start+current)/2))`; both 4dp ROUND_HALF_UP.

### State machine coverage

All 10 machines: Client (suspend/reinstate), DonationBatch (RECEIVED→IN_SORT gated on a CHECKED_IN SORTING-shift signup covering now; auto IN_SORT→SORTED at declared count; SORTED→CLOSED with SoD), Item (full 13-transition graph incl. quarantine/restock/reject, rotation phase-out/in, recycling seal), ReferralPartner (suspend), ClientVisit (checkout with per-line zone cascade; void with reservation release and no un-redemption), Voucher (redeem/revoke/lazy EXPIRED), VolunteerShift (auto LOCK↔OPEN at capacity, complete/cancel signup cascades), ShiftSignup (check-in window, ownership-scoped cancel/check-in), SpecialDrive (lazy UPCOMING→ACTIVE→CLOSED + manual close), SeasonalRotation (execute window-gated, cancel), RecyclingBatch (sweep/seal/pickup with SoD and validation order weight→state→SoD).

### PRD interpretation decisions (prose admitted multiple readings)

1. **Line-add on a non-CHECKED_IN visit → `ERR_ITEM_NOT_AVAILABLE`** (not `ERR_INVALID_STATE`), per PRD §3.3's explicit sentence and the state-machine precondition, over the generic validation-7 default.
2. **`voucher_bonus_applied`** = the voucher's full `bonus_items` whenever one is redeemed (not the post-24-cap residue); the cap clips only `general_allowance`.
3. **Signup overlap scan excludes the target shift itself**, so a duplicate signup on the same shift surfaces `ERR_ALREADY_SIGNED_UP` (priority 20) rather than being shadowed by `ERR_SHIFT_OVERLAP` (19) — otherwise rule 20 is dead code.
4. **Drive window conflict**: conflict iff `new_start < existing_end + 7d AND existing_start < new_end + 7d` (gap < 7 days or overlap → conflict; exactly 7 days clearance allowed). All same-type drives counted regardless of status.
5. **Lazy status flips bump `version`/`updated_at`** (they are status transitions per §2.5); zone `version` also bumps on every stock-affecting cascade (stock, distribute, return, quarantine, restock, rotation), per the skill's cascade rule; reservation alone never touches the zone.
6. **`items_distributed_total`** = items currently in `DISTRIBUTED` status (symmetric with `recycled_items_total`); **`unique_clients_served`** = distinct clients with a `CHECKED_OUT` visit; credit totals sum non-null provisional/final amounts across all batches.
7. **Sweep requires ACCUMULATING** (`ERR_INVALID_STATE` otherwise) — scaffold validation 7 lists the recycling batch states for action endpoints.
8. **Pagination bounds enforced**: `limit` outside 1–100 or `offset` < 0 → `ERR_INVALID_REQUEST` (PRD 2.3 states min/max); invalid enum values in list filters → 400 ("types/enums valid", priority 5).
9. **Window/interval semantics**: shift check-in and sorting-staff coverage use inclusive `[start_at, end_at]`; signup overlap uses half-open intervals (back-to-back allowed); drive windows inclusive both ends; rotation window inclusive.
10. **Ownership vs existence**: ownership is checked without the entity only when the path id itself is the scope (`/clients/{id}`, `/referral-partners/{id}` self-checks → 403 before 404); where the check needs the record (visit/voucher/signup), 404 precedes 403.
11. `meta.api_request_timestamp` is taken from the logical clock ("every timestamp the server writes… never from the wall clock").

Verified: fresh-boot empty store across `start.sh` restarts (per-test-server isolation contract), default-port boot, guarded install (no pip re-run), plus ~120 passing assertions across three harnesses covering envelope shape, RBAC/ownership, validation ordering, all calculations, both SoD rules, OCC 412s, lazy voucher/drive advancement, quota carryover (2→3→5→7 across months), rotation phase gating, and report fields.

## Step 7: Run Tests and Iterate — 2026-08-14T21:45:00.000Z

All 8 rounds pass 87/87. The exit criterion is met — the task is stable.

**Summary**

- **Iterations run**: 3 sweeps (1 diagnostic sweep → 1 confirmation sweep after the fix, which surfaced 1 infrastructure-noise failure → 1 final clean sweep at 8×87/87).

- **Tests deleted**: none.

- **Fixes applied to `test_helpers/`**: none.

- **Fixes applied to `test_suite/`**: `test_suite/test_05_lines_limits_and_checkout.py` — 5 tests issued `api.add_line(visit_id, item_id_string, headers)` with a **bare string as the JSON body** instead of the PRD-required object `{"item_id": ...}`:
  - `TestCategoryCaps::test_category_cap_coats_third_rejected`
  - `TestGeneralAllowanceLimit::test_general_allowance_breach_rejected`
  - `TestRollingItemCap::test_rolling_item_cap_boundary`
  - `TestDrivePools::test_drive_bonus_pool_and_category_exemption`
  - `TestDrivePools::test_drive_item_stockable_while_upcoming_but_line_blocked`

  Why: PRD §3.3 states "The request names an `item_id`" and the §2.6 cascade runs request-shape validation (`ERR_INVALID_REQUEST`, priority 5) before the business rules (priority 7+). The implementation correctly rejected the malformed body at the shape layer, so the tests never reached the asserted business errors. All 5 call sites were wrapped in `{"item_id": ...}`, matching the fixture helper (`fixtures.add_line` → `factories.add_line_payload`) and the dict-passing tests in the same file. No assertion was weakened; the asserted error_ids all trace verbatim to PRD line 147 (four-limits paragraph) and line 196/181 (`ERR_DRIVE_NOT_ACTIVE`).

- **Fixes applied to `implementation/`**: none. The implementation was correct throughout — every failure was either the test-payload bug above or host noise.

- **Flakiness disposition**: round 6 of the confirmation sweep failed once on `test_recycling_credit_provisional_and_final_variants_diverge` with `ConnectionResetError` mid-setup. Server log `/tmp/prd_bench_server_57485.log` showed that test's server generation received an external **SIGTERM** ("Terminated" — the only SIGTERM among ~90 generation boundaries; every runner-initiated kill is a LISTEN-filtered `kill -9`). No code path inside the round's own processes sends SIGTERM mid-run, the app never saw the request (no traceback, request absent from the access log), and the host concurrently runs multiple other task sweeps (126 runner/pytest processes; port registry up to 24 holders). Not attributable to any task artifact and not fixable in-scope; the final sweep confirmed 8×87/87.

## Step 8: Finalize PRD — 2026-08-14T21:50:00.000Z

Verification complete. PRD_FINALIZED.md is in place as a byte-identical copy of PRD.md, and no edits were warranted.

### Summary

**Line counts / delta**: `PRD.md` 330 lines vs `PRD_FINALIZED.md` 330 lines — 0% delta, byte-identical (verified with `cmp`).

**Changes**: none.

The only Step 7 fixes were test-side payload-shape corrections in `test_suite/test_05_lines_limits_and_checkout.py` (bare JSON string body → `{"item_id": ...}` object at 5 `api.add_line` call sites). This class of fix produces no PRD edit because the PRD already uniquely determines the behavior:

- PRD §3.3 (line 145): "The request names an `item_id`" — pins the required body field.
- PRD §2.6 (line 97): the validation cascade runs request-shape validation ("required fields present, types and enum values valid...") as `ERR_INVALID_REQUEST` at priority 5, strictly before state permissibility and the temporal/capacity/quota business rules at priority 7+. A bare string body contains no `item_id`, so `ERR_INVALID_REQUEST` must surface before any of the business errors those 5 tests asserted (`ERR_ITEM_LIMIT_EXCEEDED`, `ERR_CATEGORY_LIMIT_EXCEEDED`, `ERR_ROLLING_ITEM_CAP_EXCEEDED`, `ERR_DRIVE_NOT_ACTIVE`).

The implementation matches this exactly, and the 5 tests were pure fixture bugs contradicting the PRD and the suite's own canonical helper. No assertion was weakened; no impl change occurred.

**Per-edit pre-edit search log** (zero edits committed; the one candidate subject was investigated and rejected):

- **Candidate subject**: line-add request-body shape enforcement (`POST /closet/visits/{id}/lines`).
- **(a) Subject identified**: whether PRD needs extra wording to pin that a non-object/malformed body is rejected with `ERR_INVALID_REQUEST` before the four business limits.
- **(b) Impl paths enumerated and read**: `implementation/routes/lines.py` (lines 25-117: `add_line` — `get_body()` first, then `item_id` presence/type → `ERR_INVALID_REQUEST` 400, then item existence, then availability, then the four limits in PRD order at lines 65-103); `implementation/util.py` (lines 70-79: `get_body()` — non-dict JSON body raises `ERR_INVALID_REQUEST`; shared body-shape gate used across all routes); `test_helpers/factories.py` (line 29: `add_line_payload` returns `{"item_id": item_id}`), `fixtures.py` (lines 287-293), `api_client.py` (line 50), fixed call sites in `test_05_lines_limits_and_checkout.py` (lines 48, 76, 101, 139, 185, 221, 261).
- **(c) Wording adjustment**: none — no edit committed. PRD §3.3's "The request names an `item_id`" plus §2.6's shape-at-priority-5 cascade already describe exactly what `get_body()` + `add_line()` do, so any additional sentence would risk over-pinning against paths Step 7 never exercised. Under the NO-NEW-MISMATCH rule, the correct action is a byte-identical copy.

**Other step_7_diff items**: none applicable — no test deletions, no `test_helpers/` fixes, no `implementation/` fixes; the single confirmation-sweep failure was external SIGTERM host noise, not attributable to any task artifact.

## Step 9: Complete PRD — 2026-08-14T22:00:00.000Z

The diff is complete and correct. All 16 edit operations applied cleanly.

### Summary

**Produced:** `workspace/PRD_COMPLETED.md`

**Source vs. completed:** `PRD_FINALIZED.md` (330 lines / 48,194 chars) → `PRD_COMPLETED.md` (332 lines / 52,144 chars); char-delta **+3,950**, line-delta **+2** (one convention paragraph added inside §2.5; all other changes are inline).

**Counts:** 22 ambiguity-pins, 2 mismatch-revisions (24 changes via 16 edits).

### Changes (one bullet each)

- §2.3 — insert — ambiguity — pinned `has_more` = (`offset` + returned items) < `total_count`, and that unparseable/out-of-range pagination or enum filter values are `ERR_INVALID_REQUEST` — implementation/response.py:29, implementation/util.py:165-205
- §2.4 — insert — ambiguity — clock endpoint applies `to_iso8601` unconditionally (no monotonicity check; backward jumps accepted) — implementation/routes/clock.py:14-19, implementation/db.py:41-42
- §2.4 — insert — ambiguity — global convention: creation-order ties (lists, rotation phase-in, sweep candidacy) break by internal insertion sequence, never identifier — implementation/util.py:191, implementation/db.py:29,56, implementation/routes/rotations.py:100,108, implementation/routes/recycling.py:61
- §2.4 — revise — ambiguity — voucher lazy expiry is also evaluated on revocation attempts — implementation/routes/vouchers.py:16-21,63-68
- §2.4 — insert — ambiguity — a drive whose whole window passed before evaluation jumps `UPCOMING`→`CLOSED` directly — implementation/services.py:66-76
- §2.4 — revise — ambiguity — drive lazy advancement also occurs at line addition and at stocking, not only on reads/check-in — implementation/routes/lines.py:55, implementation/routes/items.py:97
- §2.5 — insert — ambiguity — null-until-event convention for event timestamps, operator fields, settlement figures, and unset optional references — implementation/routes/visits.py:84-85, implementation/routes/partners.py:105, implementation/routes/recycling.py:33-37, implementation/routes/donations.py:34-35,103-109
- §2.6 — insert — mismatch — §2.6's absolute "ownership before existence" cascade contradicted impl for field-dependent scope: path-decidable ownership (client/partner self-record) is evaluated pre-existence, field-dependent ownership (visit/voucher `client_id`, voucher `partner_id`) requires loading first, so missing ids yield `ERR_NOT_FOUND` before scope — implementation/routes/visits.py:114-118, implementation/routes/vouchers.py:29-33 vs implementation/routes/clients.py:58-62, implementation/routes/partners.py:43-47
- §2.7 — revise — ambiguity — "do not accept a version field" pinned to ignore-not-reject (all unrecognized body fields ignored) — implementation/util.py:90-144
- §3.1 — insert — ambiguity — clients list supports a `status` filter — implementation/routes/clients.py:47-53
- §3.2 — insert — ambiguity — a client's visits list supports a `status` filter — implementation/routes/visits.py:103-108
- §3.3 — insert — ambiguity — remove-line with non-`ACTIVE` line or non-`CHECKED_IN` visit is `ERR_INVALID_STATE` — implementation/routes/lines.py:152-153
- §3.3 — revise — ambiguity — return bypasses every stocking check (capacity, season, drive status), not just capacity, and leaves `distributed_at`/`distributed_from_zone_id` intact — implementation/routes/lines.py:164-182
- §3.4 — insert — ambiguity — `expires_at` at/before the clock at issuance is `ERR_INVALID_REQUEST` — implementation/routes/partners.py:78-82
- §3.4 — insert — ambiguity — a `ReferralPartner` may read only vouchers issued under its own partner id (`ERR_FORBIDDEN` otherwise) — implementation/routes/vouchers.py:32-33
- §3.6 — insert — ambiguity — quarantine retains the item's `storage_zone_id` while decrementing the zone's stock — implementation/routes/items.py:113-125
- §3.7 — insert — ambiguity — overlap scan considers only other shifts; duplicate active signup on the same shift surfaces `ERR_ALREADY_SIGNED_UP`, never `ERR_SHIFT_OVERLAP` — implementation/routes/shifts.py:128-152
- §3.7 — revise — ambiguity — signup cancellation requires `SIGNED_UP` (otherwise `ERR_INVALID_STATE`) — implementation/routes/shifts.py:190-191
- §3.8 — insert — ambiguity — drive-conflict semantics: pad existing same-type windows by 7 days both sides, reject on strict overlap, exactly-7-day gap allowed, other drive's status irrelevant — implementation/routes/drives.py:48-56
- §3.8 — revise — ambiguity — execution moves the rotation `SCHEDULED`→`COMPLETED` (status previously unnamed in PRD) — implementation/routes/rotations.py:120
- §3.9 — revise — ambiguity — sweep requires the batch to be `ACCUMULATING` (otherwise `ERR_INVALID_STATE`) — implementation/routes/recycling.py:53-54
- §3.9 — insert — ambiguity — report `zone_id` is a required query parameter (missing → `ERR_INVALID_REQUEST`, unknown → `ERR_NOT_FOUND`) — implementation/routes/reports.py:27-30
- §3.9 — revise — mismatch — average-basis denominator substitutes 1 when the rounded mean is zero **or negative** (impl uses `max(1, mean)`); PRD said zero only — implementation/routes/reports.py:54-57
- §3.9 — insert — ambiguity — defined the network-wide totals: items currently `DISTRIBUTED`, distinct clients on `CHECKED_OUT` visits, items currently `RECYCLED`, sums of non-null provisional/final credits — implementation/routes/reports.py:66-84

Everything else in the implementation (endpoint table, role lists, state machines, check orderings, allowance/quota/credit formulas, posture thresholds, OCC fields, envelope shapes, 201/200 split) was verified against the PRD and already pinned uniquely, so no further changes were made.
