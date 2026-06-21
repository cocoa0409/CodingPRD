# Worklog — task_0445_bed_and_breakfast

Scenario: Bed & Breakfast / Boutique Inn: room inventory & rate, peak/two-night minimum, breakfast & dietary, direct-booking vs OTA, deposit & cancellation tier, housekeeping & turnover, occupancy/lodging tax remittance, gift certificate & package

Difficulty: Expert (§0.4 Expert band)

## Step 1: Create Task Directory — 2026-06-21T01:28:23.000Z

Task directory `tasks/task_0445_bed_and_breakfast/` pre-assigned/reserved (index auto-increment overridden to avoid ID contention with 4 sibling pipelines). Directory and `workspace/` subdir already existed; reused as-is. No scan of tasks/ performed.

## Step 2: Generate Scaffold (Expert band) — 2026-06-21T01:57:05.000Z

All work is complete and verified. Here is the summary.

Generated a complete Expert-band scaffold for **task_0445_bed_and_breakfast** (Bed & Breakfast / Boutique Inn). All three files written and `scaffold_lint.py` returns **VERDICT: clean lint** (511 setup/trigger calls checked, all FK reverse-reachability satisfied).

**Files** (all under `tasks/task_0445_bed_and_breakfast/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (1328 lines)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — §1.8, single top-level key (1161 lines)
- `SCAFFOLD_CORNER_DESIGN.yaml` — §1.9, single top-level key (1772 lines)

**Complexity profile**: primary archetype temporal_windowing + secondary pricing_engine; layers = cascading_side_effects, dual_variant_calculation, optimistic_concurrency, rate_threshold_triggers; flat topology; parallel state-machine shape; peer_roles.

**Scaffold contents (SCAFFOLD.yaml)**:
- **11 entities**: Inn, Room, RatePeriod, Package, Guest, GiftCertificate, Booking, BreakfastPlan, PaymentLedgerEntry, HousekeepingTask, TaxRemittance.
- **6 state machines** including a **parallel** Booking machine (reservation_status × payment_status on one row), a **cyclic** GiftCertificate (ACTIVE↔DEPLETED), and branching HousekeepingTask/BreakfastPlan.
- **7 calculations**: room_charge (round-per-night-then-sum), package_charge, lodging_tax, deposit_due (DIRECT 30%/floor vs OTA full), cancellation_refund (tiered, provisional vs final variants), gift_restore_on_cancel (cash-first waterfall), tax_remittance_total (ESTIMATED vs FINAL).
- **19 validations** (priority-ordered), **50 endpoints** (26 mutations + 24 reads incl. a `/_clock/set_current_utc` test-driving endpoint defaulting to 2026-01-01T00:00:00Z), **20 error codes**, **4 roles** (Innkeeper/Guest entity-backed, Housekeeper/FinanceManager opaque), **2 concurrency rules** (OCC on Room.version at booking-confirm; OCC on GiftCertificate.version at redeem-gift).

**Difficulty design (§1.8)**: all 9 rules × 2 instances = **18 instances**, every formula-derived assert pinned to a code-computed literal (room_charge=40002 round-then-sum, tax 13050, deposit 10000, refund tiers 100/50/10/0%, etc.).

**Corner design (§1.9)**: **43 active instances + 7 `excluded_because` stubs** spanning all 8 applicable claim-extraction-guide sections (entities 11, state_machines 8, calculations 5, validations 8, endpoints 2, rbac 4, cross-cutting layers 4, consistency 1).

**Key findings/decisions during generation**: (1) `api_prefix` had to be `/inns/{inn_id}` for the lint's collection-segment deriver to recognize nested collections; (2) added single-resource GETs (RatePeriod, Package, BreakfastPlan, PaymentLedgerEntry) and a `payment-ledger-entries` filtered list to satisfy FK reverse-reachability; (3) added a `pay-deposit` business endpoint + `ERR_PAYMENT_EXCEEDS_BALANCE` so the `DEPOSIT` ledger enum value is producible and the cash-first refund waterfall is meaningfully testable; (4) reworked the state-vs-fiscal priority-conflict instance to use a CANCELLED+unmet-deposit booking so both checks genuinely fire. No forbidden concurrency vocabulary; no `id` used in any business decision (only `created_at ASC` tie-break). Did not look at any sibling task directory, per the hard constraint.

## Step 3: Copy Shared Files — 2026-06-21T01:57:10.000Z

Copied root `INSTRUCTION.md` → `tasks/task_0445_bed_and_breakfast/workspace/INSTRUCTION.md` (1424 bytes). Bash-only step, no subagent.

## Step 4: Generate PRD — 2026-06-21T02:03:26.000Z

Generated `workspace/PRD.md` (272 lines / ~6,500 words) for the Bed & Breakfast / Boutique Inn domain. Did NOT read, grep, or reference `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`. Worked only from `SCAFFOLD.yaml`, the skill spec, the §2.2 verbatim source file, and the example PRD.

**Structure:** §1 Introduction; §2 Global Specifications (2.1 RBAC, 2.2 Response Structure verbatim, 2.3 Pagination, 2.4 Logical Clock, 2.5 Common Resource Properties, 2.6 Monetary/Rates/Rounding round-then-sum vs round-half-up, 2.7 OCC both rules, 2.8 Hierarchical Consistency/Cascades, 2.9 Nested Retrieval + validation precedence); §3 Business Logic (9 lifecycle subsections); §4 Endpoint table (all 50 endpoints); §5 Error catalogue (all 20 error IDs).

**Hard Contract reports (all PASS):**
- Contract 1 — Field-Name Coverage: 69 required, 69 present, 0 missing. PASS.
- Contract 2 — Rule Coverage: validations priority orderings expressed; 2/2 OCC rules expressed; all state-machine transitions expressed (both Booking axes, GiftCertificate, HousekeepingTask, BreakfastPlan, TaxRemittance) with side-effect cascades; 7/7 calculations reconstructible step-for-step; all 20 error IDs matchable to triggers. PASS.
- Contract 3 — §3 Path Purity: 334 backtick tokens scanned, 0 path/method tokens in §3. PASS.

Calculations rendered in precise prose: per-night floor-then-sum room charge (highest-multiplier tie-broken by earliest created_at), DIRECT 30% vs OTA full deposit (first-night floor applied after rounding), 14/7/1/0-day refund tiers with OTA-under-14-days override, cash-first/gift-second refund waterfall, ESTIMATED-superset/FINAL-subset remittance variants.

## Step 5: Generate Unit Tests — 2026-06-21T02:19:18.000Z

Generated complete test infrastructure for `task_0445_bed_and_breakfast` from the two design indices only (no freelance SCAFFOLD walking).

**Tests emitted: 78 total**
- **Queue A (Difficulty): 35 tests** covering **17 of 18** instances (≥2 each)
- **Queue B (Corner): 43 tests** covering **41 of 43** non-stub instances (≥1 each)

**Instances skipped: 3** (gaps left as gaps — no weakening, no xfail)
- *validation-priority / unique-derivability* (1): `Difficulty/priority_pair_validation_conflict/date_range_beats_occupancy_on_create` — PRD §3.2 lists the date-range and occupancy checks as a flat set with no stated relative ordering; §2.9's generic "lower-priority-number rule wins" does not expose priority numbers to a PRD-only reader, so the date-range-beats-occupancy outcome is not uniquely derivable. (The sibling `invalid_state_beats_deposit_on_confirm` IS kept — PRD §3.4 explicitly states the state guard precedes the deposit check.) The two singular checks are still covered via queue B's `occupancy_exceeded_rejected` and `invalid_date_range_rejected`.
- *applies_to-scope / endpoint-titular* (2): `Corner/endpoints/filtered_booking_list_by_channel` and `Corner/endpoints/filtered_housekeeping_by_room` — PRD §2.3 specifies only `limit`/`offset` as list query params; no PRD prose states a `channel` or `room_id` filter on those list endpoints (the endpoint table only titles them). A PRD-only implementer could omit those filters.

All 7 `excluded_because:` stubs correctly NOT translated; no broken design pointers.

**Test file layout** (`test_suite/`): test_01_pricing_and_deposits.py (11), test_02_tax_remittance.py (4), test_03_reservation_lifecycle.py (14), test_04_cancellations_and_gifts.py (12), test_05_room_booking_conflicts.py (9), test_06_validations_and_occ.py (14), test_07_crud_rbac_and_reads.py (14).

**`test_helpers/`**: full Stage-1 set (`types.py` with correct `common_fields` branching — Guest and PaymentLedgerEntry carry only id+created_at; `api_client.py` with 56 endpoint methods; `api_errors.py` registering all 20 error→HTTP mappings; `assertions.py`, `factories.py`, `constants.py`, `test_users.py` with entity-backed Guest identity-threading; substantial `fixtures.py` with composite confirmed/checked-out/breakfast/remittance preambles).

**Audits passed**: 78 tests / 78 `Design:` tags (exactly one each); all 92 PRD citations verbatim-verified; no skip/xfail; all files compile and all 78 tests collect under pytest.

**Notable PRD-coverage gaps surfaced**: (1) no stated precedence between date-range and occupancy booking-creation checks; (2) bookings/housekeeping-tasks list endpoints have scaffold filter params (channel, room_id) with no PRD prose.

## Step 6: Generate Implementation — 2026-06-21T02:19:18.000Z

Generated a complete Python + Flask implementation in `workspace/implementation/`.

**File layout**: start.sh (foreground launcher; guards pip install on `import flask`, reads `$PORT` default 10000, binds 0.0.0.0, execs app.py, ~5s boot), app.py (all 50+ routes), calculations.py, pricing.py, db.py (in-memory Store), clock.py, errors.py, response.py, middleware.py, helpers.py, serialize.py, requirements.txt.

**Storage/OCC/clock**: pure in-memory dicts on a single module-level Store; nothing seeded (fresh import = empty store). Monotonic `_seq` counter for stable created_at ASC tiebreak. OCC: confirm checks expected_room_version vs Room.version (ERR_STALE_ROOM_VERSION/412), redeem-gift checks expected_gift_certificate_version (ERR_STALE_GIFT_VERSION/412); optional convenience guards on retire/void/file checked only when supplied; every mutation bumps version + refreshes updated_at. Clock starts at 2026-01-01T00:00:00Z, settable via POST /_clock/set_current_utc; all tier/expiry/no-show/turnover dates read it.

**Calculations**: room_charge (floor-per-night × highest-multiplier RatePeriod, tie→earliest created_at, then sum), package_charge, lodging_tax (round-half-up), deposit_due (DIRECT 30% round-half-up then max first-night floor; OTA full), cancellation_refund (14/7/1-day tiers + OTA <14-day override), gift_restore_on_cancel (cash-bucket-first waterfall), tax_remittance_total (ESTIMATED=CONFIRMED+CHECKED_IN+CHECKED_OUT, FINAL=CHECKED_OUT only), net_inn_revenue.

**State machines**: Booking dual-axis reservation_status/payment_status with all side effects (confirm→DEPOSIT_HELD+room bump; checkout→SETTLED+spawn housekeeping+room bump; cancel→refund/forfeit ledger+gift restore+breakfast cascade+room bump; no-show→FORFEITED+cascade); GiftCertificate (ACTIVE/DEPLETED/EXPIRED/VOID + restore-to-ACTIVE); HousekeepingTask (PENDING→IN_PROGRESS→DONE / →SKIPPED); BreakfastPlan (REQUESTED→CONFIRMED→CANCELLED gated on live parent); TaxRemittance (OPEN→FILED + double-remit guard). Validation precedence per PRD §2.9: auth→forbidden→booking-owner→not-found→invalid-request→cross-inn→domain rules in priority order (double-booking p70 before deposit p80 on confirm).

**PRD ambiguities resolved**: (1) net_inn_revenue/OTA commission rounding → round-half-up (consistent with §2.6); (2) refund ledger when fully gift-funded → always one negative REFUND entry = full refund_cents when >0, restore gift remainder, cash bucket fills first; (3) payment_status when cancelling $0-paid booking → left unchanged (PRD silent); (4) "most recent non-SKIPPED housekeeping task" turnover gate → latest by creation order, no-task room treated as fresh; (5) unrecognized X-User-Role → ERR_UNAUTHENTICATED. One bug fixed during self-test: Python 3.9 datetime.fromisoformat can't parse trailing Z → added tolerant _parse_iso helper.

## Step 7: Run Tests and Iterate — 2026-06-21T02:40:06.000Z

**Iterations run:** 3 sweeps total (1 baseline + 2 fix-validation). Final sweep: all 8 parallel rounds **77/77 passed, 0 failed, 0 errors**.

### Baseline failures (4 tests, consistent across all 8 rounds — not flaky)
1. `test_overlapping_confirm_rejected_double_booked` — setup `ERR_DEPOSIT_NOT_MET`
2. `test_overlapping_confirm_leaves_second_booking_pending` — setup `ERR_DEPOSIT_NOT_MET`
3. `test_confirm_against_retired_room_rejected` — expected `ERR_RESOURCE_RETIRED`, got `ERR_INVALID_STATE`
4. `test_double_remit_rejected_after_first_filing` — expected error, filing succeeded

### Tests deleted (1)
- **`test_confirm_against_retired_room_rejected`** (test_05) — *ERROR-IDENTITY SILENCE*. PRD §3.4 requires "the room to be `ACTIVE`" for confirmation but names **no error_id** for that confirm-time gate (it explicitly names error_ids for the double-booking, deposit, non-PENDING-state, and stale-version gates only). §3.2's `ERR_RESOURCE_RETIRED` is scoped verbatim to *booking creation*, not confirm. Two divergent PRD-faithful impls exist (`ERR_INVALID_STATE` for "room not ACTIVE" vs. reusing `ERR_RESOURCE_RETIRED`), so the assertion is not uniquely derivable. The companion `test_confirm_against_retired_room_leaves_pending` (booking stays PENDING after a rejected confirm — which IS derivable) was kept. Scaffold rule that drove generation: `Difficulty/cross_entity_state_dependency/confirm_requires_room_active`.

### Fixes applied to `test_suite/` (test-vs-PRD consistency, STEP 2)
- **test_05_room_booking_conflicts.py** `_confirm_via_gift` — redeemed a hardcoded 10000 toward a 4-night DIRECT booking whose actual `deposit_due_cents` is 12000 (30% of 40000), so confirm failed the deposit gate. Changed to redeem the booking's real `deposit_due_cents` (PRD §3.3 channel policy + first-night floor). Fixed both failing overlap tests.
- **test_02_tax_remittance.py** `test_double_remit_rejected_after_first_filing` — setup opened `rem2` *after* `rem1` was filed, so per PRD §3.9 ("both variants consider only bookings whose `remitted` flag is still false") `rem2`'s pool was empty and filing was a vacuous success. Reordered to open both remittances *before* filing either, so both freeze the same unremitted booking into their swept sets at open time; filing `rem1` stamps it remitted, then filing `rem2` finds the already-remitted booking in its frozen swept set → `ERR_ALREADY_REMITTED`.

### Fixes applied to `implementation/`
- **app.py** `create_tax_remittance` / `file_tax_remittance` — the file handler **re-resolved** the sweep pool at filing time (`_sweep_pool`), which drops already-remitted bookings and makes `ERR_ALREADY_REMITTED` unreachable, contradicting PRD §3.9 ("stamps `remitted` true on every booking **in the swept set**", the set "record[ed] at open time"). Changed to freeze the swept booking ids at open (`_swept_booking_ids`, an internal underscore key the serializer hides) and at file time check/stamp against that frozen set.
- **app.py** `__main__` — silenced Werkzeug per-request logging + dev-server banner and set `use_reloader=False`. This eliminated intermittent "API server could not be restarted" boot-timeout errors that appeared on randomly-varying tests under the 8x-concurrent per-test-server reboot load (host contention, not a logic race). After this change every round runs uniformly at ~51s with zero restart errors.

**Final sweep result: 8/8 rounds, 77/77 passed, 0 failed, 0 errors.**

**Orchestrator re-verification (independent re-run):** Step 7 subagent's final sweep left no persisted results files (cleaned at start of each round), so the orchestrator re-ran the full 8-round parallel sweep. Result: all 8 rounds **passed=77 total=77 failed=0 errors=0**; `results.{1..8}.json` persisted to `workspace/implementation/`. Note: registry showed holders=9–12 during the run (sibling pipelines concurrently active on the same host, as expected); free-port-per-round isolation held, no collisions.

## Step 8: Finalize PRD — 2026-06-21T02:43:22.000Z

Step 7 had non-zero iterations (1 deletion, 2 test_suite fixes, 2 impl fixes) → Step 8 NOT skipped. Produced `workspace/PRD_FINALIZED.md`.

**Line counts:** PRD.md = 272, PRD_FINALIZED.md = 272 (insertion within an existing §3.4 paragraph line; +29 words, ~+0.4% by word count, 0% by line count).

### Changes (1 edit)
- **§3.4 (The Reservation Lifecycle) — insert — pinned the confirm-time room-`ACTIVE` gate to `ERR_INVALID_STATE`, evaluated after the deposit-coverage check — `implementation/app.py:728-730`**

### Per-edit pre-edit search log
**Edit 1 — confirm room-ACTIVE error_id**
- (a) Subject: the error raised when confirming a booking whose room is not `ACTIVE` (RETIRED), and where that check sits in the confirm gate ordering.
- (b) Impl paths enumerated/read: grepped all `ACTIVE`/`RETIRED`/`ERR_INVALID_STATE`/`ERR_RESOURCE_RETIRED` sites in app.py. Read `confirm_booking` (app.py:700-740) — order is p60 PENDING guard → recompute money → p70 double-booking → p80 deposit → room-`ACTIVE` check raising `ERR_INVALID_STATE` (728-730) → p90 OCC. Confirmed `create_booking` (app.py:502-505) handles the creation-time RETIRED-room gate separately with `ERR_RESOURCE_RETIRED` (already in PRD §3.2) — distinct from confirm.
- (c) Wording adjustment: scoped the new sentence to "evaluated after the deposit-coverage check" (matching impl: after p80, before p90); avoided claiming any priority number or ordering relative to the p90 OCC check, keeping wording consistent with the full confirm path and the separate creation-time `ERR_RESOURCE_RETIRED` gate in §3.2.

### Items deliberately NOT edited (traced to step_7_diff, found not to need a PRD change)
- Tax-remittance swept-set freeze (create/file_tax_remittance, app.py:1228-1316): PRD §3.9 already determines this (lines 186/188 describe frozen-at-open swept set + `ERR_ALREADY_REMITTED`). The Step 7 impl fix moved impl back into compliance with existing PRD prose; no edit.
- Two test_suite/ fixture fixes (`_confirm_via_gift` real deposit; `rem2` open-ordering): pure fixture bugs aligning tests to behavior PRD already pins (§3.3 line 134; §3.9 line 186). No PRD edit.
- `__main__` logging/reloader change (app.py:1327+): operational boot-stability only, no behavioral change. No PRD edit.

## Step 9: Complete PRD — 2026-06-21T02:51:02.000Z

Produced `workspace/PRD_COMPLETED.md` by copying `PRD_FINALIZED.md` and applying 18 minimal in-paragraph edits via a full PRD-vs-implementation scan. No new sections/paragraphs; line count unchanged (272 → 272).

**File metrics:** source PRD_FINALIZED.md = 272 lines / 40325 chars; PRD_COMPLETED.md = 272 lines / 44820 chars; char delta +4495; 18 changed lines.

**Counts:** ambiguity-pins: 13 · mismatch-revisions: 5

**Per-change:**
- §2.1 — insert — ambiguity — unrecognized `X-User-Role` string → `ERR_UNAUTHENTICATED` — middleware.py:26-27
- §2.3 — insert — ambiguity — out-of-range `limit`/negative `offset`/non-integer → `ERR_INVALID_REQUEST` — helpers.py:13-35
- §2.4 — insert — ambiguity — invalid/missing `to_iso8601` → `ERR_INVALID_REQUEST`; clock-set returns 200 — app.py:85-92
- §2.7 — insert — ambiguity — convenience guards checked only if supplied; void→`ERR_STALE_GIFT_VERSION`, retire-room/retire-package/file→`ERR_STALE_ROOM_VERSION`, HTTP 412 — app.py:187-189,300-302,439-440,1296-1298
- §3.1 — revise — mismatch — room `name` "unique within the inn" not enforced; duplicates accepted — app.py:133-153
- §3.2 — insert — ambiguity — guest must book for self: `guest_id`==`X-User-ID` else `ERR_NOT_BOOKING_OWNER`, after FK checks — app.py:490-491
- §3.2 — revise — mismatch — guest `email` "unique within the inn" not enforced; duplicates accepted — app.py:311-326
- §3.2 — revise — mismatch — `guest_count` < 1 → `ERR_INVALID_REQUEST` (not `ERR_OCCUPANCY_EXCEEDED`) — app.py:474; helpers.py:87
- §3.2 — insert — ambiguity — `net_inn_revenue_cents` commission = round-half-up(`total_cents`×`ota_commission_bps`/10000), recomputed at create, may be present pre-payment — pricing.py:62-66
- §3.2 — insert — ambiguity — fresh booking defaults: `refund_cents`=0, `cancelled_on`=null, `remitted`=false — app.py:526-528
- §3.3 — insert/revise — ambiguity — redeem fields all required (`ERR_INVALID_REQUEST`); OCC mismatch (`ERR_STALE_GIFT_VERSION`, 412) checked before sufficiency conditions — app.py:624-647
- §3.5 — insert — ambiguity — refund==0 & nothing paid: no ledger entry, `payment_status` unchanged — app.py:856-857
- §3.5 — revise/insert — ambiguity — single `REFUND` entry magnitude = cash portion when any cash refunded, else gift portion; gift restored LIFO across redemptions — app.py:879-924
- §3.5 — revise — mismatch — refund-quote applies no reservation-status guard (any state); `days_before` clamped ≥0 — app.py:659-675
- §3.6 — insert — ambiguity — `dietary_flags` non-list/out-of-set → `ERR_INVALID_REQUEST`; `VEGAN` materializes `VEGETARIAN`; stored deduped+sorted; bad `booking_id`→`ERR_NOT_FOUND` — app.py:1022-1044
- §3.6 — insert — ambiguity — breakfast cancel from other status → `ERR_INVALID_STATE`; guest create/cancel must own parent booking → `ERR_NOT_BOOKING_OWNER` — app.py:1035,1112-1117
- §3.8 — insert — ambiguity — expiry computed dynamically at redemption; server never writes `EXPIRED` to stored `status` — app.py:639
- §3.9 — insert (×2) — ambiguity — swept-set identity frozen at open time; filing stamps that frozen set, not a re-sweep — app.py:1256,1304

Tests used only as auxiliary cross-reference; implementation was the sole alignment authority.

---

## Pipeline complete — 2026-06-21T02:51:02.000Z

All 9 steps finished. Final state: **77/77 tests passing across 8/8 parallel stability rounds**. Artifacts in `tasks/task_0445_bed_and_breakfast/`: SCAFFOLD.yaml + 2 design indices; worklog.md; test_helpers/ + test_suite/ (77 tests); workspace/ with INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ (Python+Flask, start.sh) and results.{1..8}.json.
