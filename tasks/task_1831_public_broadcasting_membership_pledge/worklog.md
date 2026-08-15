# Worklog — task_1831_public_broadcasting_membership_pledge

## Step 1: Create Task Directory — 2026-08-14T19:22:00.000Z

Task directory `tasks/task_1831_public_broadcasting_membership_pledge/` and `workspace/` were created by the pipeline launcher (pre-done per invocation args; index 1831 assigned by launcher, not scanned).

## Step 3: Copy Shared Files — 2026-08-14T19:23:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1831_public_broadcasting_membership_pledge/workspace/INSTRUCTION.md`.

## Step 2: Generate Scaffold — 2026-08-14T19:46:00.000Z

All checks pass. All three files are written and lint-clean.

## Summary

Generated the scaffold for task 1831 (Public Broadcasting Membership & Pledge Drive) purely from the scenario description plus the skill spec — no sibling tasks were inspected.

**Files written (all three confirmed):**
- `/home/ubuntu/github/CodingPRD/tasks/task_1831_public_broadcasting_membership_pledge/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1831_public_broadcasting_membership_pledge/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1831_public_broadcasting_membership_pledge/SCAFFOLD_CORNER_DESIGN.yaml` (single top-level key `scaffold_corner_design`)

**Core dimensions:**
- **Entities: 12** (MembershipLevel, Premium, PremiumInventoryLot, Donor, Membership, PledgeDrive, OnAirBreak, Pledge, PremiumReservation, MatchingChallenge, UnderwritingCredit, NFFSReport) — inside the Expert 10–15 band
- **Endpoints: 45** — above the Expert 20–32 guideline band; this is deliberate and mechanical: the lint's FK reverse-reachability hard rule (f) forces one GET per FK across 12 cross-referenced entities, and the 5-state drive lifecycle requires five distinct action endpoints. Every endpoint is load-bearing (state reachability, FK reachability, or error triggerability); none are CRUD padding. The skill's §0.4 counts are explicitly "guidelines, not hard rules" while FK reachability and testability-completeness are enforced hard rules.
- **Errors: 20** (inside Expert 18–30 band), each exercised by at least one difficulty or corner instance
- **State machines: 5** — Pledge (parallel payment_status × fulfillment_status dimensions), Membership (cyclic ACTIVE→GRACE→LAPSED→REINSTATED_PENDING→ACTIVE), PledgeDrive (branching with revert DRAFT↔SCHEDULED→ON_AIR→CLOSED→RECONCILED), PremiumReservation (HELD→COMMITTED/RELEASED), NFFSReport (DRAFT→FINALIZED↔AMENDED amendment cycle)

**§0.5 difficulty rules — 2 instances each (18 total):**
1. `dual_variant_calc`: NFFS PROVISIONAL-vs-FINAL revenue (29500 vs 20000 on identical data); premium inventory FIFO-vs-weighted-average valuation (5500 vs 6000)
2. `combinatorial_formula`: mode (a) 3+-input level-qualification tiering (SUSTAINER 600/mo passes where ONE_TIME 600 fails); mode (b) pinned per-pledge-floor-then-sum rounding order (max(0, 1000−1500)=0 + 5000 = 5000, vs 4500 under the wrong order)
3. `non_linear_state_machine`: Membership lapse/reinstate cycle; Pledge parallel payment×fulfillment dimensions
4. `transitive_cascade`: depth-3 payment→membership reactivation→donor lapse_count reset; depth-2 write-off→reservation release→lot counter rebalance
5. `priority_pair_validation_conflict`: state-vs-business_constraint (ERR_DRIVE_NOT_OPEN beats ERR_LEVEL_OR_PREMIUM_INELIGIBLE); state-vs-business_temporal (ERR_INVALID_STATE beats ERR_BREAK_OVERLAP on a live drive)
6. `boundary_precision_check`: matching challenge MET at exactly goal (>= comparator, 9999 OPEN → +1 cent → MET); reservation rejected at exactly available_qty == 0
7. `cross_entity_state_dependency`: Pledge→PledgeDrive (capture requires ON_AIR); Pledge→Membership (sustainer payment requires ACTIVE/GRACE)
8. `resource_temporal_overlap`: OnAirBreak half-open + 5-minute buffer (18:24 rejected, 18:25 accepted); PledgeDrive pure half-open with no buffer (1-day overlap rejected, exact-touch allowed)
9. `compensating_invariant`: pay-then-decline restores drive.collected_cents to 0 with zero drift; reserve-then-release restores lot identity available+reserved+committed+written_off == total_qty

**Corner design: 31 active instances + 1 excluded-because stub** across all nine claim-extraction-guide sections (entities 5, state_machines 6, calculations 3, validations 5, endpoints 2, errors 4, rbac 3, cross_cutting_layers 3, consistency_model 1).

**Verification:** `scaffold_lint.py` verdict block, verbatim:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

(45 endpoints, 12 entities, 18 §1.8 instances, 31 §1.9 instances, 430 calls scanned, 0 violations.) Additionally audited: enum closure (removed a dead CANCELLED break state), trigger↔side-effect bidirectional match (added missing challenge-progress decrement on write-off, drive/donor resync on premium waive), deterministic FIFO lot selector with pinned eligibility/ranking/tie-break/empty-pool fallback, half-open fiscal-year windows pinned for all NFFS aggregates, logical clock default fixed at 2026-08-01T00:00:00Z, and placeholder closure (all `${var}` references trace to earlier `captures:`).

## Step 4: Generate PRD — 2026-08-14T19:52:00.000Z

All contracts PASS. PRD generation complete.

## Summary

**Output written:** `/home/ubuntu/github/CodingPRD/tasks/task_1831_public_broadcasting_membership_pledge/workspace/PRD.md`

**Line count:** 313 lines

**Section list:**
- # Public Broadcasting Membership & Pledge API — Product Requirements Document
- ## 1. Introduction
- ## 2. Global Specifications & System-Wide Principles
  - 2.1. User and Role-Based Access Control
  - 2.2. API Response Structure (verbatim from `section-2.2-response-structure.md`)
  - 2.3. Pagination
  - 2.4. Common Resource Properties and Identifier Conventions
  - 2.5. Hierarchical Consistency and Cascading Side Effects
  - 2.6. Money, Precision, and Rounding
  - 2.7. Optimistic Concurrency Control
  - 2.8. The Logical Clock
  - 2.9. Validation Ordering
- ## 3. Business Logic & Workflows
  - 3.1. Configuring Levels and Premiums
  - 3.2. Donor Registration and Membership Lifecycle
  - 3.3. Drive Scheduling and On-Air Programming
  - 3.4. Membership Period Transitions and the Lapsed-Member Cycle
  - 3.5. Pledge Capture Across Channels
  - 3.6. Premium Reservation, Shipping, and Waiver
  - 3.7. Matching Challenge Progress and Latching
  - 3.8. Payment Posting and the Three-Deep Cascade
  - 3.9. Decline and Write-Off: Compensating Reversals
  - 3.10. Underwriting Credits
  - 3.11. NFFS Reporting and Segregation of Duties
  - 3.12. Premium Inventory Valuation
- ## 4. Endpoint Definitions (4-column table, 44 endpoints)
- ## 5. Error Code Catalogue (2-column table, 20 errors)

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoints[].input/query/path params + common: 73 required, 73 present, 0 missing
Status: PASS
```

```
Rule coverage check (spot-verified):
- errors[]: 20 checked, 20 mentioned with backticks in §2/§3, 0 missing
- concurrency_rules[] OCC: 2 checked (expected_drive_version on break-create with ERR_STALE_DRIVE_VERSION/412; expected_pledge_version on payments with ERR_STALE_PLEDGE_VERSION/412), both fully expressed
- roles: 3 checked (StationAdmin, MembershipCoordinator, PhoneVolunteer), all named with identity: opaque prose
- validation priority ordering: 14 levels expressed in §2.9 with explicit ordering language
- state enum values: all 34 distinct states (membership, pledge payment/fulfillment, drive, break, challenge, reservation, NFFS report, channel, kind, variant) appear as exact UPPERCASE backticked strings
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 418
- tokens starting with /: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Confirmation:** `workspace/PRD.md` was written successfully. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, read, or referenced.

## Step 6: Generate Implementation — 2026-08-14T20:05:00.000Z

Done. Here is the summary.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1831_public_broadcasting_membership_pledge/workspace/implementation/`):

- `start.sh` — executable launcher
- `requirements.txt` — flask>=3.0
- `app.py` — Flask entry point, blueprint registration, ApiError/404/405/generic exception handlers producing the scaffold envelope
- `db.py` — in-memory stores (dicts keyed by id), logical clock (default `2026-08-01T00:00:00Z`), UUID/timestamp/version helpers
- `errors.py` — all 20 error IDs with exact HTTP statuses from the scaffold catalog
- `response.py` — success/error envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more` in meta)
- `middleware.py` — `X-User-ID`/`X-User-Role` extraction, role recognition, RBAC checks
- `validators.py` — body well-formedness (priority 0 → `ERR_INVALID_REQUEST`), pagination parsing (limit 1–100, default 10; offset default 0), not-found helper, created_at-ascending sort
- `routes/levels_premiums.py` — membership levels, premiums, inventory lots
- `routes/donors_memberships.py` — donors (case-insensitive email uniqueness), memberships, reinstate, filtered list
- `routes/drives.py` — drive CRUD + lifecycle (schedule/unschedule/go-live/close/reconcile), breaks with OCC + 5-minute half-open-buffer overlap rule, matching challenges, underwriting credits
- `routes/pledges.py` — pledge capture (auto-reservation when stock available, sustainer conversion), payments with OCC + 3-deep cascade (membership period extension, LAPSED→ACTIVE win-back with `lapse_count` reset, drive/donor resync), decline/write-off with compensating reversals and 60-day window, premium reservation (FIFO lot selection), ship, waive
- `routes/reservations.py` — reservation get/list/release (release drops pledge back to `AWAITING_RESERVATION`)
- `routes/nffs_clock.py` — NFFS draft/finalize/amend with segregation of duties, PROVISIONAL/FINAL revenue variants, FY half-open calendar window, logical clock setter driving ACTIVE→GRACE→LAPSED transitions
- `services/core.py` — `pledge_net_collected` (FMV deduction only when premium selected + RESERVED/SHIPPED + not waived), level ranking by `min_annual_cents` tie-break code ASC, latched challenge MET at `>=` goal, drive/donor rollup deltas, calendar-month extension

**Endpoint count:** 45 routes implemented — the full §1.5 endpoint table (verified by decorator count).

**State storage:** in-memory only. All entities live in module-level dicts in `db.py`; nothing is seeded at startup (no `seed_*` anywhere; boot state is empty, verified via a fresh `bash start.sh` returning `data: []` from list endpoints). The logical clock resets to the PRD default on every boot, so per-test-server restarts are clean.

**start.sh contract confirmed:** reads `$PORT` (default 10000 via `os.environ.get("PORT", "10000")` in `app.py`), binds `0.0.0.0`, and runs in the foreground via `exec python3 app.py`. The `pip install` is guarded by `python3 -c "import flask"` so per-test reboots skip reinstall.

**Verification:** three smoke suites run against fresh boots (85 assertions total) covering auth/RBAC, duplicate codes, OCC 412s on both version fields, break/drive overlap boundaries (exactly +5min allowed, half-open adjacent drives allowed), level/premium eligibility, FMV deduction math (6000 gross − 1500 FMV = 4500 net), drive/donor/challenge rollups and compensating reversals, challenge latching at exact goal, sustainer conversion, write-off 60-day window, membership extension (max(end, now) + 12/1 months), GRACE/LAPSED clock transitions including direct ACTIVE→LAPSED jump, win-back with `lapse_count` reset, NFFS PROVISIONAL vs FINAL variants, segregation of duties, and error-priority spot checks. All passed. Note: the task's `test_suite/` directory is currently empty (unit tests not yet generated), so verification was via these smoke tests plus a boot through the exact evaluator contract (`bash start.sh` from `./implementation/`).

## Step 5: Generate Unit Tests — 2026-08-14T20:25:00.000Z

All generation and verification is complete. Both directories were written and pass structural audit.

## Summary

**Task:** task_1831_public_broadcasting_membership_pledge — test infrastructure + suite generated from the two design indices only.

### Test counts
- **Queue A (Difficulty):** 34 tests covering 17 of 18 instances (each with exactly ≥2 tests). Tags verified as `Design: Difficulty/<rule_id>/<instance.name>`.
- **Queue B (Corner):** 30 tests covering 30 of 31 non-stub instances (≥1 each). The 1 stub (`Corner/errors/error_insufficient_inventory_excluded_because`) was not translated — its `excluded_because` cross-reference to `reservation_rejected_at_exact_zero_available` resolves and that difficulty instance carries 2 tests.

### Skipped instances (2)
1. **`Difficulty/dual_variant_calc/premium_inventory_fifo_vs_weighted_average`** — not observable: PRD §3.12 describes the FIFO/weighted-average algorithms, but no PRD endpoint returns an inventory valuation (the recipe's trigger `GET /premiums/{id}/lots` exposes only lot counters), so the asserted values 5500/6000 cannot be observed by any PRD-only implementer.
2. **`Corner/endpoints/pledges_filtered_list_by_drive_and_status`** — no PRD coverage: §4 says only "List pledges with filters" and never names the `drive_id`/`payment_status` filter parameters, so the specific filtered-read behavior is not uniquely derivable.

### Design-recipe adaptations (reachability fixes, asserted values unchanged)
Two recipes created a level with `min_annual_cents: 6000` and then captured pledges below it, which the PRD's level check would reject before the asserted behavior: the exact-goal challenge test (9999 + 1 cents) and the challenge/drive-rollup tests (4000-cent pledges). The generated tests lower the level minimum (1 / 1000 / 4000 cents respectively) so the scenarios are reachable; every literal expected value from the YAML is asserted verbatim. Also, payment-posting responses are validated leniently (`get_success_data` / 2xx) because PRD §4's 200-vs-201 rule is ambiguous for payment posting (modifies the pledge vs. creates a payment record).

### Files written
- `test_helpers/` (9 files): `__init__.py` (barrel), `types.py` (12 entity TypedDicts + 11 enums), `api_client.py` (33 endpoint methods), `api_errors.py` (20 errors + framework status-map registration), `assertions.py` (per-entity assertions + lot-conservation invariant), `factories.py`, `constants.py` (clock start, 30-day grace, 60-day write-off window, 5-minute break buffer), `test_users.py` (3 opaque-role header constants + per-user-id builders for SoD tests), `fixtures.py` (tiered composites incl. `setup_on_air_drive`, `setup_station`, `setup_station_with_challenge`, `setup_lapsed_membership`, `setup_nffs_mixed_pledges`).
- `test_suite/` (8 files): `conftest.py` + `test_01_catalog_levels_and_auth.py` (6), `test_02_drives_breaks_scheduling.py` (11), `test_03_pledge_capture.py` (9), `test_04_payments_and_membership.py` (11), `test_05_premiums_inventory.py` (11), `test_06_reversals_writeoffs_totals.py` (9), `test_07_nffs_reporting.py` (7).

### Verification performed
- `pytest --collect-only`: 64 tests collected, no import errors.
- Tag audit: every test has exactly one Design tag resolving to a real non-stub instance; no untagged/dual-tagged/dangling tags.
- Citation audit: all 104 quoted PRD citations across 64 docstrings grep verbatim against `workspace/PRD.md` (≥8-word window per docstring).
- No `skip`/`skipif`/`xfail` markers; no "scaffold" references in generated code; all files compile.

## Step 7: Run Tests and Iterate — 2026-08-14T20:32:00.000Z

All 8 rounds pass 64/64. Clean exit.

## Summary

- **Iterations run:** 2 (initial 8-round sweep: 62/64 ×8, same 2 failures in every round — deterministic, not flaky; post-fix 8-round sweep: 64/64 ×8).

- **Tests deleted:** none.

- **Fixes applied to `test_suite/`** (both failures were test bugs; implementation was PRD-faithful):
  - `/home/ubuntu/github/CodingPRD/tasks/task_1831_public_broadcasting_membership_pledge/test_suite/test_06_reversals_writeoffs_totals.py` — `TestDeclineCompensation::test_decline_restores_drive_collected_total`: called `pay_in_full(pledge)`, which (a) was never imported (NameError) and (b) would have left the pledge `PAID`, a state from which PRD §3.9 forbids decline ("moves a pledge from `PLEDGED` or `PARTIAL` to `DECLINED`"). Replaced with `post_payment_ok(pledge, 5000)` (PARTIAL, declinable) and updated the pre-decline drive assertion to `collected_cents == 5000`; post-decline assertions (both totals → 0) unchanged.
  - Same file — `TestDeclineCompensation::test_decline_restores_donor_lifetime_and_records_reason`: setup used `capture_and_pay(...)` then declined a `PAID` pledge, correctly rejected by the implementation with `ERR_INVALID_STATE` (409). Changed setup to `capture_pledge` + `post_payment_ok(pledge, 5000)`; pre-decline donor `lifetime_given_cents` assertion updated 12000 → 5000; the covered rule (§3.9 "The donor's `lifetime_given_cents` decrements by the pledge's `net_collected_cents`" + `decline_reason` recording) is still exercised exactly.

- **Fixes applied to `test_helpers/`:** none needed.

- **Fixes applied to `implementation/`:** none — the 409 on declining a `PAID` pledge is PRD-required behavior (§3.9 decline gate + §2.9 priority 5 state check), corroborated by the passing `test_decline_on_written_off_pledge_terminal_lockdown`.

- **Generator feedback:** both failures trace to the unit-test generator emitting a decline-after-full-payment setup, which violates the PRD §3.9 decline source-state constraint (`PLEDGED`/`PARTIAL` only); the missing `pay_in_full` import is a secondary generation slip in the same test.

## Step 8: Finalize PRD — 2026-08-14T20:38:00.000Z

Done. `PRD_FINALIZED.md` is written and is a byte-for-byte copy of `PRD.md` — the correct outcome here, because both Step 7 items were pure test fixture bugs against behavior the PRD already pins, not PRD silence or PRD/impl mismatch.

## Summary

**Line counts / delta:** `PRD.md` = 312 lines, `PRD_FINALIZED.md` = 312 lines, 0% delta (`diff` reports IDENTICAL). File: `/home/ubuntu/github/CodingPRD/tasks/task_1831_public_broadcasting_membership_pledge/workspace/PRD_FINALIZED.md`

**Changes:** none — zero edits committed.

**Rationale per Step 7 item:**

- `TestDeclineCompensation::test_decline_restores_drive_collected_total` — pure fixture bug (missing `pay_in_full` import + declining a `PAID` pledge). PRD §3.9 already determines the behavior: "a `PhoneVolunteer` moves a pledge from `PLEDGED` or `PARTIAL` to `DECLINED`" — `PAID` is excluded by enumeration, and §2.9 priority 5 pins the rejection as `ERR_INVALID_STATE` (409). The impl matches exactly (`routes/pledges.py:382-385`). The rule the fixed test still covers (drive `collected_cents` decrement by `net_collected_cents`) is verbatim in §3.9. No edit.
- `TestDeclineCompensation::test_decline_restores_donor_lifetime_and_records_reason` — same class of fixture bug (declined a `PAID` pledge via `capture_and_pay`). The covered rules — "The donor's `lifetime_given_cents` decrements by the pledge's `net_collected_cents`" and `decline_reason` recording — are verbatim in PRD §3.9. No edit.

**Per-edit pre-edit search log (candidate edits evaluated and rejected):**

Edit candidate 1 — "pin that declining a `PAID` pledge is rejected with 409":
- (a) Subject: decline source-state gate and its error.
- (b) Impl paths enumerated and read: `routes/pledges.py:375-390` (`decline_pledge`: role check → `reason` body validation at priority 1 → state gate `payment_status not in ("PLEDGED","PARTIAL")` → `ERR_INVALID_STATE` 409 → `_compensating_reversal` → set `DECLINED`); `routes/pledges.py:54-75` (`_compensating_reversal` shared cascade — drive `pledged_cents`/`collected_cents` decrements, latched challenge progress decrement, `RESERVED`→`RELEASED` reservation compensation, donor `lifetime_given_cents` decrement, `decline_reason` recording); `routes/pledges.py:393-409` (`write_off_pledge` — shares the identical state gate at lines 400-403); grep for `DECLINED` across all impl `.py` files — only other hit is `routes/nffs_clock.py:45` (DECLINED pledges contribute 0 to NFFS membership revenue, matching §3.11). PRD re-read: §3.9 (lines 205-211), §2.9 (lines 112-135).
- (c) Wording adjustment: none committed — PRD §3.9's source-state enumeration plus §2.9 priority 5 already fully determine the behavior; any added sentence (e.g., "declining a `PAID` pledge is rejected with `ERR_INVALID_STATE`") would restate existing pins and, per the NO-NEW-MISMATCH rule, risk narrowing the shared state gate that also serves write-off, whose PRD wording deliberately does not enumerate source states. Rejected as unnecessary.

Edit candidate 2 — "pin donor lifetime / decline_reason cascade details":
- (a) Subject: compensating-reversal cascade contents.
- (b) Impl paths enumerated: `routes/pledges.py:54-75` (`_compensating_reversal`, shared by decline and write-off), `services/core.py` helpers `challenge_progress_sub` / `donor_lifetime_sub` (invoked from the cascade), plus the two fixed tests' assertions.
- (c) None committed — every cascade element the tests exercise is already verbatim in PRD §3.9 paragraph 2. Rejected as pure fixture-bug territory.

## Step 9: Complete PRD — 2026-08-14T20:52:00.000Z

Done. PRD_COMPLETED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1831_public_broadcasting_membership_pledge/workspace/PRD_COMPLETED.md`.

## Summary

**Source:** `PRD_FINALIZED.md` (312 lines, 39,568 chars) → `PRD_COMPLETED.md` (314 lines, 45,116 chars). Delta: +2 lines, +5,533 chars.

**Counts:** 34 ambiguity-pins, 6 mismatch-revisions (40 change items across 19 edit sites).

### Mismatch revisions
- §2.9 item 1 — revise — mismatch — PRD claimed all body well-formedness (incl. missing fields) fires before auth (401); impl rejects only malformed/non-object JSON before auth, and runs field-level validation after auth/role, interleaved endpoint-specifically with 404 checks, with the break `pitch_level_code` check after the drive-state check — `validators.py:11-23`, `routes/pledges.py:84-96`, `routes/drives.py:66-90`
- §3.3 — revise — mismatch — drive-close cascade said challenges go `EXPIRED` "with its progress frozen"; impl latches status but still decrements `progress_cents` on later reversals — `routes/drives.py:238-242`, `services/core.py:140-143`
- §3.4 — revise — mismatch — reinstatement was conditioned on the pledge reaching `PAID`; impl fires the `REINSTATED_PENDING`→`ACTIVE` cascade on any posted payment, even a partial one — `routes/pledges.py:364-366`, `services/core.py:178-186`
- §3.5 — revise — mismatch — PRD said `premium_waived` true with no premium selected yields `NO_PREMIUM`; impl yields `WAIVED` — `routes/pledges.py:201-202`
- §3.8 — revise — mismatch — PRD conditioned SUSTAINER `PAID` on covering the first installment; impl sets `PAID` on any successful SUSTAINER payment and keeps it — `routes/pledges.py:344-346`
- §4 — revise — mismatch — payment posting returns HTTP 201 with the updated pledge, not 200 per the modify-convention — `routes/pledges.py:368`

### Ambiguity pins
- §2.2 — insert — unknown path / unsupported method → `ERR_NOT_FOUND` (404); other unhandled faults → `ERR_INVALID_REQUEST` (400) — `app.py:35-49`
- §2.3 — insert — non-integer/out-of-range `limit`/`offset` rejected with `ERR_INVALID_REQUEST` (400) — `validators.py:82-102`
- §2.3 — insert — `has_more` = `offset` + returned page size < `total_count` — `response.py:41`
- §2.3 — revise — sort ties break by `id` ascending — `validators.py:116-117`
- §2.7 — insert — OCC version check evaluated after existence/state checks, before remaining business rules — `routes/drives.py:82-96`, `routes/pledges.py:301-318`
- §2.8 — insert — all server-emitted timestamps (entity `created_at`/`updated_at`, meta `api_request_timestamp`) stamped from the logical clock; clock setter not monotonicity-enforced; transitions never revert — `db.py:67-76`, `response.py:17`, `routes/nffs_clock.py:161-168`
- §2.9 item 4 — insert — capture body-reference existence order: donor, membership, drive, break, challenge, premium — `routes/pledges.py:99-122`
- §3.1 — insert — level thresholds are required non-negative integers (0 allowed) — `routes/levels_premiums.py:23-24`
- §3.1 — insert — `active` list filter takes `true`/`false` (case-insensitive), else 400 — `routes/levels_premiums.py:49-56`
- §3.1 — insert — `fair_market_value_cents` required non-negative; unknown `membership_level_code` → `ERR_NOT_FOUND` (404) — `routes/levels_premiums.py:70-78`
- §3.1 — insert — `unit_cost_cents` non-negative integer — `routes/levels_premiums.py:112`
- §3.2 — insert — duplicate donor email (case-insensitive) → `ERR_DUPLICATE_CODE` (409) — `routes/donors_memberships.py:27-29`
- §3.2 — insert — unresolvable `donor_id`/`level_code` on membership open → `ERR_NOT_FOUND` (404) — `routes/donors_memberships.py:75-80`
- §3.3 — insert — `goal_cents` required non-negative integer — `routes/drives.py:35`
- §3.3 — insert — break window containment is inclusive on both ends; out-of-window → `ERR_BREAK_OVERLAP` (422); unknown `pitch_level_code` → `ERR_INVALID_REQUEST` (400) after the drive-state check — `routes/drives.py:88-104`
- §3.4 — insert — clock boundary comparisons are inclusive (`>=`); one jump crossing both boundaries moves `ACTIVE`→`LAPSED` with a single `lapse_count` increment; `REINSTATED_PENDING` unaffected by clock — `services/core.py:214-239`
- §3.4 — insert — payment during `GRACE` returns membership to `ACTIVE`, sets `current_period_start` to payment time, same extension rule — `services/core.py:203-206`
- §3.4 — insert — month arithmetic is calendar-based with day-of-month clamping — `services/core.py:150-156`
- §3.5 — insert — break reference validated for existence/drive-membership only (status/window not consulted); membership status unchecked at capture — `routes/pledges.py:108-142`
- §3.5 — insert — "stock available" = some lot with `available_qty` ≥ 1; auto-reservation is quantity 1 against the FIFO-first lot (`received_at`, then `created_at`) with lot counter compensation; pledge `collected_cents`/`net_collected_cents` start at 0 — `routes/pledges.py:190-241`
- §3.6 — insert — explicit `lot_id` unknown → 404; wrong-premium or under-quantity lot → `ERR_INSUFFICIENT_INVENTORY` (422); inactive premium → `ERR_LEVEL_OR_PREMIUM_INELIGIBLE` (422) — `routes/pledges.py:447-474`
- §3.6 — insert — waiver sets the pledge's `premium_waived` flag true — `routes/pledges.py:565`
- §3.7 — insert — challenge creation not restricted by drive status — `routes/drives.py:267-286`
- §3.8 — insert — SUSTAINER payment capped at the pledge's per-installment `amount_cents`, over → `ERR_PAYMENT_AMOUNT` (422) — `routes/pledges.py:331-335`
- §3.9 — insert — write-off `reason` is likewise recorded as `decline_reason` — `routes/pledges.py:73`
- §3.10 — insert — underwriting credits recordable against a drive in any status — `routes/drives.py:312-329`
- §3.11 — insert — finalization recomputes all three revenue lines from current records; reads return stored values (no recompute on GET) — `routes/nffs_clock.py:78-83, 116-136`
- §3.11 — insert — amendment recomputes the three lines under PROVISIONAL and retains the prior `finalized_by_user_id` — `routes/nffs_clock.py:139-154`
- §3.12 — insert — valuation variants are offline calculations; the API exposes no valuation endpoint and no lot write-off operation, so `written_off_qty` stays 0 — (no valuation code exists; route inventory confirmed)
- §4 table — revise ×3 — pinned exact list filters: memberships (`status`, `donor_id`, `sustainer`), pledges (8 fields), reservations (`pledge_id`, `premium_id`, `lot_id`, `status`) — `routes/donors_memberships.py:126-139`, `routes/pledges.py:275-279`, `routes/reservations.py:29-32`

No new sections added; all changes are in-paragraph inserts/revisions or table-cell edits. Nothing was pinned that the implementation does not exhibit.
