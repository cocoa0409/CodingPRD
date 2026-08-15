# Worklog — task_1421_high_school_athletic_training_injury

## Step 1: Create Task Directory — 2026-08-13T05:51:00.000Z

Task directory `tasks/task_1421_high_school_athletic_training_injury/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher. Treated as DONE per instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T07:19:00.000Z

Scaffold generation complete. All three artifacts are written and pass `scaffold_lint.py` with a clean verdict on the first full run after fixes.

**Files**
- `/home/ubuntu/github/CodingPRD/tasks/task_1421_high_school_athletic_training_injury/SCAFFOLD.yaml` (§1.0–§1.7 only)
- `/home/ubuntu/github/CodingPRD/tasks/task_1421_high_school_athletic_training_injury/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1421_high_school_athletic_training_injury/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Counts**
- 17 entities, 12 state machines, 13 calculations, 12 validation priority rows, 95 endpoints (incl. `POST /_clock/set_current_utc` with the mandatory `2026-08-01T00:00:00Z` default), 43 error codes (every one triggered by at least one design instance), 7 roles, 2 OCC concurrency rules
- 25 difficulty instances (all nine rules ≥2; rules 1, 2, 3, 4, 6, 7, 9 carry 3 each)
- 62 corner entries (58 active + 4 `excluded_because` stubs) across all nine claim-extraction sections
- Lint: `VERDICT: clean lint` — 837 §1.8/§1.9 calls scanned, 0 violations

**Design decisions worth noting**
- Archetype: compliance/audit primary + temporal-windowing secondary; flat topology; cyclic state-machine shape; segregation-of-duties role model (recorder≠verifier on physicals, author≠approver on EAPs, requester≠approver on restock orders, trainer≠physician on concussion clearance). SoD is reachable because nurses can record physicals and ADs can request orders.
- Athlete `participation_posture` is a derived, posture-driven gate (5 tiers, pinned evaluation order) recomputed from physicals, baselines, injuries, RTP protocols, referrals, and clock sweeps — never directly settable.
- Dual-variant calcs in three domains: heat policy (DISTRICT vs STATE_ASSOCIATION breakpoints, e.g. 90.5°F = EXTREME vs SEVERE), inventory valuation (FIFO vs WAC_RUNNING vs WAC_EXACT — three-way divergence 203/201/202 on one ledger, rounding order pinned per-transaction), physical expiry (13-month vs school-year).
- Boundary contrasts deliberately mixed: heat tiers and RTP dwell and lightning all-clear and injury close and notification escalation are `>=`-inclusive; referral `due_by` expiry is strictly `>`.
- Temporal overlap with two different interval semantics: trainer PRIMARY assignments use bare half-open `[start,end)` (back-to-back allowed); venue bookings use 30-minute buffered half-open windows.
- Cascades: referral NOT_CLEARED → RTP terminate → injury status → posture (depth 3); RTP regress → injury → posture + guardian notification; weather reading → event suspend → assignments ON_HOLD with `pre_hold_status` snapshot/restore; restock receive → ledger append → stock/status recompute → budget committed→realized.
- OCC anchors are genuine create-with-supersede races: RTP protocol creation on `InjuryEvaluation.version`, EAP activation on `Venue.version`.
- RBAC: six staff roles entity-backed by `Staff.role_type`; `ParentGuardian` is opaque, ownership-matched to `athlete.guardian_user_id`; TeamCoach is read-only with medical records denied.
- All formula-derived assert literals (valuations, coverage counts, reorder clamps, tier boundaries) were executed against the pinned formulas and match; a mechanical clock-vs-timestamp replay of every recipe caught and fixed two ordering bugs before lint.
- One deliberate exception: the word "simultaneous" appears only inside the verbatim scenario string (domain meaning: overlapping games); no concurrency-rule framing uses forbidden vocabulary.

## Step 3: Copy Shared Files — 2026-08-13T07:20:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1421_high_school_athletic_training_injury/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T07:55:00.000Z

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1421_high_school_athletic_training_injury/workspace/PRD.md` — 420 lines, ends at the §5 error table with no audit footer.

**Section structure**

- **§1 Introduction** — 2 paragraphs, business-context angle (trainer's five-hat burden → design pillars: derived posture, logical clock, segregation of duties, append-only ledger, OCC).
- **§2 Global Specifications** (10 subsections): 2.1 Roles/RBAC with per-role `identity:` translations and the three ownership rules; 2.2 verbatim response envelope (byte-identical to `section-2.2-response-structure.md`, verified mechanically); 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending); 2.4 Logical clock (`2026-08-01T00:00:00Z` startup default, `to_iso8601`/`current_utc`, full sweep semantics); 2.5 Common resource properties (explicit `updated_at`/`version` absence for `EnvironmentalReading` and `InventoryTransaction`); 2.6 Derived-state reconciliation and cascade/version semantics; 2.7 OCC (both rules fully expressed); 2.8 Left-to-right nested retrieval with all 14 not-found error IDs; 2.9 Validation priority pipeline (auth → ownership → existence → OCC → state → safety → temporal → referential → aggregate → fiscal, plus schema short-circuit note); 2.10 Money/measurement precision (integer cents, round-half-up, 1-decimal WBGT, whole-second temporal comparisons).
- **§3 Business Logic** (9 subsections, lifecycle strategy): 3.1 Athletes/clearance (physicals, baselines, 5-gate posture machine with all 8 reason codes); 3.2 Venues/EAPs; 3.3 Events/coverage (staff registry paragraph added here to home `sport_certifications`); 3.4 Heat/lightning/weather suspension; 3.5 Injuries; 3.6 Referrals; 3.7 RTP; 3.8 Guardian notifications; 3.9 Supplies/valuation/purchasing.
- **§4 Endpoint table** — 4 columns, all 95 endpoints present with exact scaffold roles.
- **§5 Error catalogue** — 2 columns, all 43 error IDs with correct HTTP statuses.

**Hard contract reports**

```
Field coverage check:
- entities[].fields + endpoint inputs + query params + path params: 149 required, 149 present, 0 missing
  (131 as standalone backticked tokens; 18 path params covered verbatim inside §4's backticked path tokens)
Status: PASS

Rule coverage check:
- validations[] priority ordering: expressed globally in §2.9 + locally at restock-approve and RTP-advance
- concurrency_rules[] OCC rejections: 2/2 (write endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 + supersede rationale)
- state_machines[].transitions: all from/to pairs, preconditions with error IDs, and side effects rendered (incl. 3-hop NOT_CLEARED cascade, pre_hold_status snapshot/restore, bubble-up/down coverage loop)
- calculations[]: 13/13 in precise prose (both expiry variants, both heat tables with inclusive lower bounds, lightning 30/45-min holds with inclusive radius and strict-before/inclusive-at boundary, coverage base+modifiers clamped 1–4, FIFO/WAC_RUNNING/WAC_EXACT, pinned 7-step reorder suggestion, 24h dwell, 14/3/1-day referral windows with strict expiry, 24h escalation, 30-day close)
- validations[] conditions: all 43 error IDs matchable to trigger prose in §2/§3
- sibling branches: event cancel ×3 states, referral expiry ×2, begin-care OPEN|REFERRED, acknowledge SENT|ESCALATED, physical expiry RECORDED|VERIFIED — all rendered with equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 894
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Scattering / narrative decisions**

- OCC fields (`expected_injury_version`, `expected_venue_version`) appear in both §2.7 (contract) and the §3.7/§3.2 workflow narratives; weather-reading inputs split between §3.4 (core) and §2.9/§3.4 gate discussion; injury inputs split across §3.5 (core) and §3.1 (posture impact).
- Constants embedded in prose with unit context: "thirty-minute buffer", "twenty-four hours", "thirty days", 80.0/84.0/87.0/90.0 vs 82.0/86.0/89.0/92.0 breakpoint tables, 4-athlete / 1,000-spectator coverage bumps.
- Relationships implied through actions ("payload carrying `athlete_id`"), never declared as schema; per-entity 404 IDs enumerated once in §2.8 rather than scattered.
- `TeamCoach` medical-privacy denial rendered in §2.1 with `ERR_FORBIDDEN_ROLE` (scaffold has no per-denial error); the `UNREACHABLE` phone carrier-failure simulation rendered in §3.8 as the `FAILED` path.
- Manual complete on `ON_HOLD` deliberately framed as system-only (event-completion cascade), matching the trigger columns in the scaffold's CoverageAssignment machine.

## Step 5: Generate Unit Tests — 2026-08-13T08:50:00.000Z

All 107 tests collect cleanly. Generation complete — final summary below.

**Task**: task_1421_high_school_athletic_training_injury — full test infrastructure generated from the two design indices against the PRD.

### Output
- **`test_helpers/`** (9 modules): `types.py` (17 entities; append-only `EnvironmentalReading`/`InventoryTransaction` TypedDicts correctly omit `updated_at`/`version` per PRD §2.5), `api_client.py` (76 endpoint methods incl. `/_clock/set_current_utc`), `api_errors.py` (43 error ids, HTTP map registered with the framework), `assertions.py` (17 entity assertions + `assert_instant_equals` for timestamp-instant comparison), `factories.py`, `constants.py` (heat breakpoints, 30/45-min lightning holds, 24h dwell, 14/3/1-day referral windows, coverage cap 4), `test_users.py` (7 roles, per-instance `make_*_headers` builders for all entity-backed roles), `fixtures.py` (composite helpers: `setup_cleared_athlete`, `setup_athlete_with_rtp`, `walk_protocol_to_stage`, `setup_venue_with_active_eap`, `setup_covered_event`, `setup_approved_order`, clock/ledger helpers).
- **`test_suite/`** (12 files: `conftest.py` + 11 test files): **107 test functions**, all collecting under pytest, zero skip/xfail markers.

### Coverage
- **Queue A (Difficulty): 24/25 instances translated**, each with exactly ≥2 tests (48 tests total).
  - **Skipped (1)**: `resource_temporal_overlap/venue_booking_buffered_overlap` — fails unique derivability. PRD §3.3 says a hosted event's window "padded by a thirty-minute buffer, collides with the proposed window" — it does not pin whether the proposed window is also padded nor whether touching buffered endpoints collide. The instance's two boundary assertions (30-min gap rejected, 60-min gap accepted) flip depending on which reading an implementer picks (single- vs double-sided padding × half-open vs touching collision), so a faithful PRD-only implementation could fail either assertion.
- **Queue B (Corner): 58/58 non-stub instances translated** (1 test each). All 4 `excluded_because:` stubs were verified to resolve to real queue-A instances and were not translated: `event_weather_suspension_side_effects` → `event_suspend_resume_weather_cycle`, `priority_ordering_covered_by_difficulty` → `rtp_advance_state_vs_safety_priority`, `cascading_side_effects_covered_by_difficulty` → `referral_not_cleared_three_hop_cascade`, `dual_variant_calculation_covered_by_difficulty` → `inventory_fifo_vs_wac_running_same_ledger`.
  - **Partial facet drop (1)**: in `entities/referenced_resources_not_found_return_404`, the `ERR_BUDGET_NOT_FOUND`-at-order-creation facet was dropped (14 other resource-family 404s retained). The PRD names that trigger only in the approval narrative ("a `SupplyBudget` must exist for the order's `fiscal_year`"), so creation-time rejection is not PRD-covered; the docstring records this gap.

### Stage checks
- **Stage 1**: helpers import cleanly; 76 client methods; error map registered at import time.
- **Stage 2**: every test carries exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` tag resolving to a real instance (audit-verified: 0 missing, 0 unknown, 0 dual/untagged).
- **Citation pass**: all 107 docstrings carry PRD citations; every citation fragment ≥8 words verified verbatim against `PRD.md` (normalized whitespace) — final audit reports 0 failures.
- **Style**: no `pytest.mark.skip/skipif/xfail` anywhere; no scaffold/Table references in generated comments; `pyflakes` clean for the test suite; all modules compile; `pytest --collect-only` succeeds (107 tests).

### Design decisions worth noting
- **Timestamp comparisons use instants, not strings** (`assert_instant_equals`): the PRD pins the instants rules land on ("at the stroke of 00:00:00Z that day") but only §2.5's common fields carry a pinned 3-fractional-digit serialization; string equality on `expires_on`/`due_by`/`sent_at` etc. would fail PRD-faithful serializers like `....000Z`.
- **`version == 1` at creation** is asserted per the design indices' pre-computed literals (e.g., venue version 2 after one activation); PRD §2.5's "increments with every modification" is cited, matching repo precedent.
- **One recipe bug adapted**: `physical_self_verify_rejected`'s setup creates the athlete as SchoolNurse, which §4 forbids (AthleticTrainer/SystemAdmin only); the translation creates the athlete as SystemAdmin instead, preserving the asserted segregation rule.

## Step 6: Generate Implementation — 2026-08-13T08:30:00.000Z

Implementation complete and verified. Here is the summary.

## File structure

`/home/ubuntu/github/CodingPRD/tasks/task_1421_high_school_athletic_training_injury/workspace/implementation/`

- `start.sh` — foreground launcher; guards `pip install` behind `python3 -c "import flask"` so per-test reboots skip reinstall; `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask app, blueprint registration, error handlers (`ApiError` → scaffold envelope; 404/405 → `ERR_NOT_FOUND`), global request lock
- `db.py` — empty in-memory dicts per entity + logical clock initialized to exactly `2026-08-01T00:00:00Z` (no seeding anywhere)
- `errors.py` — all 38 error IDs with their exact HTTP statuses from the catalog
- `response.py` — envelope: `meta{api_request_id (req_*), api_request_timestamp (3-fractional-digit ISO)}`, `response_type`, `data`; list meta adds `limit`/`offset`/`total_count`/`has_more`
- `middleware.py` — `X-User-ID`/`X-User-Role` extraction, 7-role check, per-endpoint role enforcement
- `domain.py` — enums, logical-clock/date math (calendar month arithmetic), field validators, serializers, all calculations, cascades, clock sweep
- `routes/core.py` (staff, athletes, clearance view, physicals, baselines, shared list/pagination helper), `routes/venues_events.py` (venues, activity-status, EAPs, events, coverage assignments, weather readings), `routes/medical.py` (injuries, referrals, RTP protocols, guardian notifications), `routes/supplies.py` (items, ledger, valuation, reorder suggestion, orders, budgets), `routes/clock.py`

## Coverage

- **All 76 endpoints** from the scaffold endpoint table are implemented with the declared role sets and status codes (201 creates, 200 actions/reads).
- **State machines**: Athlete posture (5 gates, strict priority, ordered `posture_reasons`), Physical (RECORDED→VERIFIED/VOIDED, sweep→EXPIRED inclusive), Baseline (CURRENT→SUPERSEDED on newer test or CONCUSSION injury, sweep→EXPIRED inclusive), EAP (draft/approve/reject/activate with venue OCC + supersede cascade), Event (SCHEDULED↔COVERED bubble, start gates, suspend/resume/complete/cancel with assignment and EVENT_SUSPENSION cascades), CoverageAssignment (acknowledge/decline/check-in/complete/cancel + ON_HOLD snapshot/restore), Injury (OPEN→UNDER_CARE/REFERRED→RTP_IN_PROGRESS→RESOLVED→CLOSED, reopen loop, 30-day close window), Referral (schedule/complete/addendum loop/close/cancel, strict->due_by expiry sweep, NOT_CLEARED 3-hop cascade), RTP protocol (advance with dwell/symptom/posture/stage-5-concussion/recurrence≥2 gates, regress, authority-gated clear, terminate, supersede via injury OCC), Notification (send/retry/acknowledge, UNREACHABLE→FAILED, 24h escalation sweep), RestockOrder (submit/approve/reject/receive/cancel with budget commit/release/realize), SupplyItem derived stock_status.
- **Calculations**: `physical_expiry` (13 calendar months at 00:00Z; STATE_SCHOOL_YEAR Aug-1 rule with month<8 cutoff), `baseline_validity` (+24 months), `athlete_participation_posture`, `heat_activity_tier` (DISTRICT/STATE_ASSOCIATION breaks, 1-decimal rounding, latest-recorded_at + latest-created tie-break, no-readings→NORMAL), `lightning_all_clear` (inclusive radius, 30/45-min holds, inclusive all-clear boundary), `event_coverage_requirement` (contact base, +tournament/+restricted≥4/+attendance≥1000 modifiers, clamp 1..4), `inventory_stock` (signed ledger), `inventory_valuation` (FIFO layers with ADJUSTMENT at last-restock cost, WAC_RUNNING per-transaction round-half-up with empty-reset, WAC_EXACT via `Fraction` with single final round-half-up), `supply_reorder_suggestion` (pinned 7-step waterfall), `rtp_stage_dwell` (24h inclusive), `referral_due_window` (14/3/1 days, exclusive expiry), `notification_escalation_window` (24h inclusive), `injury_close_window` (30 days inclusive).
- **Validation pipeline** follows PRD §2.9: headers → role → ownership → existence (left-to-right path, family-specific 404s; body FKs) → OCC (412) → state (409) → safety gates (403/409/422) → temporal (409) → reference quality (422) → aggregate (400/409/422) → fiscal (404 budget-missing, 402 exceeded).

## Storage design

Per-entity dicts keyed by server-minted UUID; records carry `id`/`created_at`/`updated_at`/`version` (version starts 1, `updated_at`+`version` bump on every stored change including cascades). `EnvironmentalReading`/`InventoryTransaction` omit `updated_at`/`version` per PRD §2.5. An internal monotonic `_seq` (never serialized) breaks ordering ties, since the frozen logical clock makes `created_at` collide. A global `RLock` serializes requests. Boot is stateless — verified by fresh-boot runs of both suites.

## Interpretation decisions worth noting

1. **"VERIFIED physical has ever existed"** — implemented as `verified_by_staff_id is not None` rather than current `status == "VERIFIED"`, because the sweep moves VERIFIED→EXPIRED and the scaffold's INELIGIBLE gate ("a VERIFIED physical exists but is EXPIRED") would otherwise be unreachable. A physical expired while still RECORDED never counts as verified.
2. **Venue overlap buffers** — conflict iff the gap between windows is strictly under 30 minutes (exactly-30-minute gap allowed), consistent with the half-open philosophy used for coverage overlap.
3. **stage_history shape** — `{stage, entered_at, exited_at, exit_reason}` with an initial open entry (`exited_at`/`exit_reason` null) appended at protocol creation; each transition closes the current entry and (for advance/regress) opens the next one.
4. **Posture-driven re-derivation of `required_trainer_count`** — recomputed for matching-sport/level events in SCHEDULED|COVERED after posture changes (per the scaffold's derived-recompute trigger).
5. **Event start/resume heat and lightning gates** use the tournament-aware (45-min/STATE) variants when `event_type == TOURNAMENT`, DISTRICT otherwise; venue-level `activity-status` always uses DISTRICT/30.
6. **Coverage assignment / weather reading / inventory transaction** not-found errors use the generic `ERR_NOT_FOUND` (the catalog defines no family-specific IDs for them).
7. **Pagination** clamps out-of-range `limit`/`offset` (default 10, min 1, max 100) rather than rejecting; lists sort by `created_at` ascending with insertion-order tie-break.

Verification: two from-scratch end-to-end suites (a ~100-assertion workflow smoke test and a ~70-assertion edge/boundary suite covering tier boundaries, tie-breaks, OCC, cascades, valuation rounding, sweeps, RBAC, and error mapping) both pass against fresh `start.sh` boots.

## Step 7: Run Tests and Iterate — 2026-08-13T09:12:00.000Z

Clean 8-round sweep achieved: **107/107 in all 8 rounds, union of failures = 0.**

## Summary

- **Iterations run:** 2 (round 1: 92/107 with 15 stable failures; round 2 after fixes: 107/107 × 8 rounds, zero flakiness).

- **Tests deleted:** none. Every failing test traced to a verbatim PRD rule; no PRD-silence or unique-derivability deletions were warranted.

- **Fixes applied to `test_helpers/`** (`/home/ubuntu/github/CodingPRD/tasks/task_1421_high_school_athletic_training_injury/test_helpers/fixtures.py`):
  1. `setup_athlete_with_rtp()` — added `physical_overrides` / `baseline_overrides` kwargs and plumbed them into `setup_cleared_athlete` (which already supported them). Five RTP tests passed these kwargs and died with TypeError before exercising any PRD behavior (fixture signature gap, STEP 2).
  2. `get_valuation()` — stopped routing through the `_ok()` helper, which demanded an `id` key in the response. PRD §3.9 defines the valuation report as `{supply_item_id, policy, quantity_on_hand, valuation_cents}` — a computed report with no resource `id`. Six valuation/conservation tests were blocked on this; the implementation's FIFO/WAC_RUNNING/WAC_EXACT arithmetic was already correct (captured responses matched expected values exactly).

- **Fixes applied to `test_suite/`** (`test_10_supplies_inventory.py::test_threshold_edit_reconciles_stock_status`):
  - The assertion `lowered["version"] == item["version"] + 1` used the creation-time snapshot, ignoring that the intervening RESTOCK ledger append recomputes `current_stock`/`stock_status` — a server reconciliation that PRD §2.6 says "refreshes `updated_at` and increments `version`". The test now re-reads the item pre-PATCH and asserts exactly +1 across the PATCH, preserving assertion strength while matching PRD §2.5/§2.6.

- **Fixes applied to `implementation/`**:
  1. `domain.py` + all four route modules — added `get_path_resource()` and applied it to all ~60 path-parameter lookups: an identifier that fails UUID parse now draws the generic `ERR_NOT_FOUND` (PRD §2.8: "An identifier that cannot be parsed at all … draws the generic `ERR_NOT_FOUND`"; §2.5 pins ids as UUID-formatted), while well-formed-but-unknown ids keep their family-specific 404s. Body references deliberately unchanged (§2.8 assigns them family-specific errors).
  2. `routes/medical.py` — corrected the `stage_history` model to the PRD §3.7 append-on-exit journal: activation opens the log empty; advance/regress/clear/terminate (including the supersede and NOT_CLEARED-report cascades) each *append* a closed entry `{stage, entered_at, exited_at, exit_reason}` for the exited stage. The old model seeded an open entry at creation and rewrote its tail, which contradicted "appends an ADVANCED/REGRESSED/CLEARED/TERMINATED history entry".

No implementation check required by the PRD was weakened; no endpoints/fields were added beyond PRD; storage remains purely in-memory.

## Step 8: Finalize PRD — 2026-08-13T09:25:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1421_high_school_athletic_training_injury/workspace/PRD_FINALIZED.md` is written — a 2-line patch of PRD.md.

## Size delta
- PRD.md: 419 lines / 73,132 chars; PRD_FINALIZED.md: 419 lines / 73,833 chars (+0.96%). Both edits are in-place paragraph revisions (lines 121 and 233); no sections added or removed.

## Changes (one bullet per edit)
- **§2.8** — revise — Split the catch-all sentence into two pinned rules: (1) a **path** identifier that cannot be parsed **as a UUID** (the §2.5 id format) draws generic `ERR_NOT_FOUND` rather than the family-specific one; (2) the families with no specific error are named (coverage assignments, environmental readings, inventory transactions), and `ERR_BUDGET_NOT_FOUND` was added to the family list; (3) body references explicitly skip the parse screen — malformed body refs still draw their family's error — `implementation/domain.py:241-254` (`get_path_resource`) and all ~60 path callsites across `routes/core.py`, `routes/venues_events.py`, `routes/medical.py`, `routes/supplies.py`; body-ref lookups at e.g. `routes/medical.py:45,181,184`, `routes/supplies.py:210,420`, `routes/venues_events.py:118,250,411,414,571`.
- **§3.7** — revise — `stage_history` pinned as an append-only log **of stage exits**: activation opens the log empty (entering stage 1 appends nothing); each advance/regress/clear/terminate — including the supersede and `NOT_CLEARED`-report cascades — appends exactly one entry, already closed at append time, recording the exited stage with that stage's `entered_at`/`exited_at` — `implementation/routes/medical.py:331-345` (`_close_stage_entry`), `385` (empty at creation), `371-374` (supersede), `252-261` (NOT_CLEARED cascade), `466,485,527,552` (advance/regress/clear/terminate).

## Diff items that required no PRD edit
- `test_helpers/fixtures.py` `setup_athlete_with_rtp()` kwargs — pure fixture signature gap; no PRD behavior involved.
- `test_helpers` `get_valuation()` bypassing `_ok()` — fixture bug; PRD §3.9 already pins the valuation response as exactly `{supply_item_id, policy, quantity_on_hand, valuation_cents}` (matches `routes/supplies.py:353-360`).
- `test_10_supplies_inventory.py` threshold-edit assertion — test bug; the +1 version across RESTOCK-reconciliation and +1 across PATCH is already determined by PRD §2.5/§2.6/§3.9.

## Per-edit pre-edit search log (NO-NEW-MISMATCH)
**Edit 1 (§2.8 identifier resolution).**
- (a) Subject: how path identifiers vs body references resolve to 404 errors.
- (b) Enumerated and grepped: `domain.py:241-254` (`get_path_resource`: UUID-parse failure → `ERR_NOT_FOUND`, unknown → family arg); every `get_path_resource` callsite (~60, grep-verified) across all four route modules, including the three generic-family users (assignments `venues_events.py:479`, readings `:628`, inventory txns `supplies.py:255`) and budgets (`supplies.py:603` → `ERR_BUDGET_NOT_FOUND`); every body-reference lookup (`db.X.get` / `in db.X`, grep-enumerated: medical.py:45,48,52,181,184; core.py:244,341; supplies.py:210,213,420; venues_events.py:118,121,250,411,414,571) — none UUID-parse-screens, all raise family errors; `clock.py` (no ids).
- (c) Adjustments: scoped the parse rule to "a **path** identifier", pinned "parsed **as a UUID**", named the three generic families, added `ERR_BUDGET_NOT_FOUND` to the enumeration (impl `supplies.py:603` + §5 catalogue), and added the explicit body-reference carve-out — all verified consistent with every enumerated path.

**Edit 2 (§3.7 stage_history).**
- (a) Subject: RTP protocol stage-history journaling semantics.
- (b) Enumerated and grep-verified every `stage_history` touchpoint: `medical.py:385` (opens empty), `331-345` (sole writer, closes at append), `371-374` (supersede cascade), `252-261` (NOT_CLEARED cascade), `466-467` (advance — entry records pre-advance stage), `485-491` (regress — records pre-reset stage), `527-533` (clear at stage 6), `552-553` (terminate), `domain.py:510` (serializer).
- (c) Wording says "the `stage` being exited, that stage's `entered_at`" (covers regress recording the pre-reset stage, staying consistent with the verbatim regress sentence "appends a `REGRESSED` history entry, returns `current_stage` to 1") and names both automatic-termination cascades so the §3.6 cascade description remains accurate.

## Step 9: Complete PRD — 2026-08-13T09:50:00.000Z

Done. `PRD_COMPLETED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1421_high_school_athletic_training_injury/workspace/PRD_COMPLETED.md`.

## Summary

**Source vs output:** `PRD_FINALIZED.md` (419 lines, 74,119 chars) → `PRD_COMPLETED.md` (421 lines, 76,982 chars; **+2 lines, +2,863 chars**). The two added lines are the new filter-semantics paragraph in §2.3; all other changes are inline.

**Counts:** 20 ambiguity-pins, 4 mismatch-revisions (24 logical changes across 20 edit sites). Walked all 6 implementation modules (`app.py`, `middleware.py`, `domain.py`, `response.py`, `errors.py`, `db.py`, `routes/{core,venues_events,medical,supplies,clock}.py`) — every endpoint, state transition, calculation, cascade, sweep, serializer, and error path. Role tables, the §5 error catalogue, filter lists, and response shapes already matched; no changes needed there.

**Changes** (section — insert|revise — ambiguity|mismatch — what — impl ref):

- §2.3 — insert — ambiguity — limit/offset clamping ([1,100], [0,∞)) and unparseable-fallback-to-default — routes/core.py:24-41
- §2.3 — insert — ambiguity — list sort ties on `created_at` broken by creation order — routes/core.py:46
- §2.3 — insert — ambiguity — filter semantics: exact match; boolean true/1/yes-false/0/no; staff unparseable→matches nothing, venue unparseable→reads false; unparseable `fiscal_year`→matches nothing — routes/core.py:53-72,107-113; routes/venues_events.py:70-73; routes/supplies.py:450-456,590-596
- §2.4 — insert — ambiguity — clock target unconstrained (may move backward) — routes/clock.py:13-18
- §2.5 — insert — ambiguity — `version` starts at 1 on creation — domain.py:278
- §2.10 — insert — ambiguity — calendar-month arithmetic clamps day to target month's last day — domain.py:113-118
- §2.10 — revise — mismatch — heat readings stored as submitted, rounded to one decimal only at tier comparison (was "recorded and compared at one decimal place") — domain.py:770; routes/venues_events.py:560-583
- §3.1 — revise — mismatch — `memory_index`/`reaction_time_ms` accept any number in range (not integers as §2.10's blanket implies) — routes/core.py:331-336
- §3.1 — revise — ambiguity — any newly recorded baseline supersedes the `CURRENT` one regardless of `test_date` ordering (was "a newer test") — routes/core.py:362-369
- §3.1 — insert — ambiguity — gate 2 "latest VERIFIED physical" = latest `exam_date`, ties by creation order — domain.py:640
- §3.1 — insert — ambiguity — gate 3 clearing referral must be for that injury — domain.py:671-676
- §3.2 — insert — ambiguity — duplicate `version_label` per venue → `ERR_INVALID_REQUEST` — routes/venues_events.py:123-127
- §3.2 — revise — mismatch — `supersedes_eap_id` validated for existence only; no same-venue enforcement (PRD said "at the same venue") — routes/venues_events.py:121-122
- §3.3 — insert — ambiguity — venue-overlap collision test is strict; endpoint-touching windows don't collide — routes/venues_events.py:259
- §3.3 — insert — ambiguity — posture-driven trainer-count re-derivation touches only `SCHEDULED`/`COVERED` events — domain.py:756-762
- §3.3 — insert — ambiguity — coverage-overlap test counts only other PRIMARY assignments in active statuses on non-`CANCELLED` events — routes/venues_events.py:424-433
- §3.4 — insert — ambiguity — the other reading type's value field is ignored and stored null — routes/venues_events.py:581-582
- §3.4 — revise — ambiguity — heat cascade triggers on venue-level district-tier EXTREME at an OUTDOOR venue with per-event recheck on the event's own table (state for TOURNAMENT); lightning strike suspends all in-progress events at the venue, indoor or outdoor — routes/venues_events.py:590-609
- §3.4 — insert — ambiguity — activity-status always uses the 30-minute district window; `lightning_hold_until` reported whenever any counting strike exists (even lapsed), null only when none — routes/venues_events.py:91-99
- §3.7 — revise — mismatch — clear-gate order pinned as state → posture → authority → dwell (PRD parenthetical had implied dwell second) — routes/medical.py:510-524
- §3.8 — insert — ambiguity — `subject` rendered from the notification type, title-cased (e.g. `Injury Initial`) — domain.py:824
- §3.9 — insert — ambiguity — `policy` parameter defaults to `WAC_RUNNING`; unrecognized value → `ERR_INVALID_REQUEST` — routes/supplies.py:343-345
- §3.9 — insert — ambiguity — under WAC policies an `ADJUSTMENT` adds quantity × current running unit cost — routes/supplies.py:300,320
- §3.9 — insert — ambiguity — ledger `RESTOCK` unit cost must be a strictly positive integer; non-RESTOCK cost stored null — routes/supplies.py:201-206

Notable deliberate non-changes: §2.9's stage order (ownership before existence) is unobservable when the target doesn't exist, and impl's per-endpoint check ordering (e.g., overlap before venue-active, stale-version before state) already conforms to §2.9; infra behaviors (405→404, catch-all 400, empty-string header edge) were left unpinned as outside the API contract.
