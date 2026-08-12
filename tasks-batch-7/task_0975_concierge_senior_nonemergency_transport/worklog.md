# Worklog — task_0975_concierge_senior_nonemergency_transport

## Step 1: Create Task Directory — 2026-08-10T00:00:00.000Z

Pre-assigned output folder `tasks/task_0975_concierge_senior_nonemergency_transport` with `workspace/` subdirectory already existed per command args; Step 1 auto-index scan skipped as instructed. Directory verified present.

## Step 2: Generate Scaffold — 2026-08-10T07:50:00.000Z

Scaffold generation complete. All three artifacts written and lint-clean.

## Deliverables

- `/home/ubuntu/github/CodingPRD/tasks/task_0975_concierge_senior_nonemergency_transport/SCAFFOLD.yaml` — §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_0975_concierge_senior_nonemergency_transport/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:` (§1.8)
- `/home/ubuntu/github/CodingPRD/tasks/task_0975_concierge_senior_nonemergency_transport/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:` (§1.9)

No sibling task under `tasks/` was inspected; the design is derived solely from the scenario text plus the skill spec.

## Design summary (harder-than-expert calibration)

- **Archetype blend**: temporal windowing (driver buffered windows, rate-card half-open windows, standing-ride generation horizon) + pricing engine (hourly/mileage/wait, tiered cancel fees, per-line rounding). Layers: selector policy, dual-variant calculation, OCC, cascading side effects. Flat topology, cyclic state shape, segregation-of-duties role model (a BillingAdmin who dispatched a ride on an invoice cannot resolve its dispute), immediate consistency.
- **Surface**: 12 entities, 52 endpoints, 43 error codes, 13 calculation rules, 14 validation priorities, 10 state machines (incl. Ride rematch cycle, Invoice dual independent dimensions issuance × dispute, ComplianceDoc renewal/expiry loop, Client auto-suspension at 3 no-shows), 7 roles with mandatory `identity:` fields, 2 OCC concurrency rules (`standing-ride-put-stale-version`, `client-patch-stale-version`), logical-clock endpoint with the mandatory `2026-05-01T00:00:00Z` default, and an ops-run checkpoint (`/ops/run-cycle`).
- **§1.8**: 20 instances, every rule ≥2 — all numeric asserts pre-computed and verified by executing the formulas in Python (quote 6300 vs final 5250; after-hours floor 2501; per-line rounding 1251+1251=2502 vs 2501; credit cap 3000→due 8200; cancel boundaries 0/1251/2501 at exactly 1440/240/239 minutes; wait grace 4500 vs 4550 at 10 vs 11 minutes; depth-3 compliance-expiry cascade vs depth-2 client-suspension cascade; credit-pool and AR compensating invariants; buffered-window vs touching-window overlap semantics).
- **§1.9**: 73 instances (65 active + 8 `excluded_because:` stubs) across all nine guide sections; every one of the 43 error codes is exercised by at least one instance; all `grounds:` resolve mechanically; all stub targets exist in §1.8.

## Lint verdict (verbatim, final run)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     12
  §1.8 instances scanned:     20
  §1.9 instances scanned:     65
  Calls scanned (§1.8+§1.9):  1053

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Fixes applied during iteration: quoted the `output:` inline dict values (`string[]` broke YAML flow mapping), quoted all `$.data[N].field` captures and bracketed `grounds:` flow items, renamed the cancel endpoint's free-text input to `cancel_note` to disambiguate it from the system-set `Ride.cancel_reason` enum, and refined the driver-overlap input set to live (non-terminal) rides only so completed/no-show rides never block future acceptances.

## Step 3: Copy Shared Files — 2026-08-10T07:52:00.000Z

Copied ./INSTRUCTION.md to tasks/task_0975_concierge_senior_nonemergency_transport/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-08-10T08:05:00.000Z

All checks pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_0975_concierge_senior_nonemergency_transport/workspace/PRD.md`.

**What was generated.** A prose PRD for the Concierge Senior Transport API with: a 2-paragraph business-context introduction; §2 with 11 subsections (RBAC with per-role `identity:` translation, verbatim §2.2 envelope block, pagination, common resource properties including the `RideEvent` no-`updated_at`/no-`version` exception, logical clock with the `2026-05-01T00:00:00Z` startup default and half-open window semantics, the 14-stage ordered validation pipeline, the two OCC rules, integer-cents/round-half-up precision, driver compliance posture, segregation of duties, and left-to-right reference validation); §3 with 10 workflow subsections scattering all fields, formulas, thresholds, and error triggers; §4 with a 4-column table of all 52 endpoints; §5 with a 2-column table of all 43 error codes.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 99 required, 99 present, 0 missing
- endpoints[].request_body (input): 67 required, 67 present, 0 missing
- endpoints[].query_params: covered via input lists; limit/offset/id/common fields also present
- Total: 114 required, 114 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 14 checked, 14 expressed in the ordered §2.6 pipeline, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 10 state machines swept (all from/to state names verified present; sibling branches — manual vs system suspend, offboard from ACTIVE vs SUSPENDED, cancel from five states, refund issuance reversals — rendered with equal density), 0 missing
- calculations[]: 13 checked, 13 fully expressed in precise prose (fare 7-step pinned order, wait boundary conditions, cancel tiers with 1440/240/239 boundaries, per-line rounding with the 2501→2502 example, credit cap floor, waterfall order, newest-first refund reversal, dual driver-load variants, 14-day horizon generation, 7-condition eligibility with ranking tie-breaks, 30-minute buffered windows, strict-< overdue AR with >= hold trigger, 3-strike no-show), 0 missing
- validations[] conditions: all matchable to their error_id in §2.6/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: expressed (family-tier 5-endpoint scope, OCC 2-endpoint scope, SoD dispute-resolves scope, fiscal gates on both booking paths), 0 missing
- entities[].fields[] structured content: defaults and initial values stated (billing_hold_limit 20,000¢, notify true, wav_surcharge 0, zero-initialized counters/flags), 0 missing
- sibling-branch symmetry: 8 groups checked, 8 symmetric, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 615
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verification: all 43 error IDs appear in §2/§3 prose, all enum/state values appear as exact strings (weekday compression was caught and fixed), §4 has exactly 52 rows matching the scaffold, §5 has exactly 43 rows. The withheld difficulty/corner design files were not read or referenced.

## Step 5: Generate Unit Tests — 2026-08-10T08:30:00.000Z

Done. Full test infrastructure and suite generated for task_0975.

## What was produced

**`test_helpers/`** (Stage 1) at `/home/ubuntu/github/CodingPRD/tasks/task_0975_concierge_senior_nonemergency_transport/test_helpers/`:
- `types.py` — 13 status/kind enums + 12 entity TypedDicts; `RideEvent` correctly omits `updated_at`/`version` (append-only per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with all 51 endpoint methods
- `api_errors.py` — all 43 error IDs with HTTP map, registered via `set_error_http_status_map`
- `constants.py` — PRD thresholds (offer timeout 30, no-show grace 15, cancel tiers 1440/240, credit cap 5000bp, NET_DAYS 14, horizon 14, travel buffer 30, strike limit 3) + STD/WAV card fixtures
- `factories.py`, `assertions.py`, `test_users.py` (with mandatory per-instance builders for the three entity-backed roles), `fixtures.py` (clock control, compliant-driver chain, dispatch/accept, happy-path execution with wait segments, late-cancel invoices, overdue-AR setup, two-driver selector environments), `__init__.py` barrel

**`test_suite/`** (Stage 2): `conftest.py` + 16 test files, **108 tests, all collecting under pytest**.

## Audit results

- **Queue A**: all 20 difficulty instances covered with ≥2 tests each (41 tests)
- **Queue B**: all 65 non-stub corner instances covered with ≥1 test each (67 tests); the 8 `excluded_because:` stubs were not translated, and all their `difficulty_instance` cross-references resolve
- **C4 tag check**: every test docstring ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line resolving to a real instance; no untagged, dual-tagged, or dangling tags
- **C1 verbatim check**: all 160 long (≥8-word) quoted spans across docstrings survive a whitespace-normalized literal grep of PRD.md (fixed bold lead-ins, ellipses, and a semicolon/period mismatch found during the sweep)
- No `skip`/`skipif`/`xfail` anywhere; no baseline/smoke/freelance tests invented outside the two indices

Two judgment calls worth noting: `client_creation_applies_defaults` was translated asserting only the PRD-stated defaults (20000/ACTIVE/0/0) — the instance's `version == 1` literal is not uniquely derivable from PRD §2.4, so it was omitted from the assertion set. `ride_computed_field_input_ignored` was kept because PRD §3.4 states the snapshot rules unconditionally ("`requires_wav` is true exactly when...", "the ride starts `SCHEDULED`"), making the asserted outcomes uniquely derivable even with extra payload fields present.

## Step 6: Generate Implementation — 2026-08-10T08:30:00.000Z

All four smoke suites pass against fresh server boots (~150 behavioral checks total). The implementation is complete.

## Report

**Delivered** a complete Python + Flask implementation of the Concierge Senior & Non-Emergency Transport API in `/home/ubuntu/github/CodingPRD/tasks/task_0975_concierge_senior_nonemergency_transport/workspace/implementation/`:

- `start.sh` — foreground launcher with the guarded dependency install (`if ! python3 -c "import flask"`), `exec python3 app.py`
- `requirements.txt` — `flask>=2.2` (already satisfied on the host; install is a no-op on per-test reboots)
- `core.py` — in-memory store (dicts keyed by UUID, nothing on disk), logical clock (default exactly `2026-05-01T00:00:00Z`), response envelope (`meta.api_request_id`/`api_request_timestamp` with 3 fractional digits, `response_type`, `data`; `limit`/`offset`/`total_count`/`has_more` in meta for lists), `ApiError`, auth helpers, body/field validators, pagination (limit default 10, 1–100, offset 0)
- `domain.py` — fare formula (Decimal `ROUND_HALF_UP` at the hourly-proration and after-hours steps only), cancellation tiers (1440 free / 240 half-up-50% / below = full minimum), driver posture, dual load metrics (`current_load_minutes` vs `day_worked_minutes`, logical-today scoped), buffered-window overlap (±30 min, touching allowed), selector (zone match → load ASC → created_at ASC), cascades, occurrence generation (today through min(ends_on, today+14))
- `billing.py` — invoice aggregation (pinned line order HOURLY/MILEAGE/WAIT/WAV_SURCHARGE/MINIMUM_ADJUSTMENT, per-line round-half-up then sum), credit application (`min(balance, floor(charges*5000/10000))`), payment waterfall (due_date ASC, created_at ASC), newest-first refund reversal with atomic `ERR_REFUND_CREDIT_SPENT`, 4-sweep ops run-cycle
- `routes_*.py` — all 51 endpoints with the §2.6 validation pipeline ordering (well-formedness → auth → role → ownership → family tier → existence → state → OCC → eligibility → temporal → occupancy → referential → fiscal → SoD)

**Verified behaviors** (fresh server per suite): envelope/error shapes, OCC 412 on both guarded endpoints, quote/final-fare math, fee boundaries (exactly 1440 free, exactly 240 → 1251 for a 2501 minimum, 239 → 2501), two late-cancel fees invoicing 1251+1251=2502, dispatch/decline/release/rematch with exclusion sets, empty-pool `data: null`, offer timeout via run-cycle, no-show grace + 3-strike auto-suspension cascade, WAV gating/surcharge, compliance-expiry driver suspension cascade, renewal chains, standing-ride create/PUT-regenerate/PAUSE/RESUME/END, billing hold at exactly-equal threshold, past_due latch, void credit restore, refund application reversal, SoD conflict, family tier/revocation error-ID semantics, and reboot state-wipe (count 0, clock back to default after restart).

**Two spec ambiguities resolved deliberately** (both follow the literal scaffold/PRD text):
1. Invoice line emission omits the after-hours multiplier (no line kind exists for it), so for after-hours floor-binding rides `charges_cents` can differ from `final_fare_cents` — each follows its own pinned rule.
2. Occurrence regeneration treats CANCELLED rides as not occupying their date (so RESUME can actually regenerate), while generation is gated on an ACTIVE series and ACTIVE client (so client-suspension gaps are not resurrected by run-cycle).

## Step 7: Run Tests and Iterate — 2026-08-10T08:53:12.000Z

RESUME NOTE (orchestrator): the prior headless run was interrupted after the Step 7 fix subagent finished its sweep but before its summary could be appended here. Step 7 is recorded as SATISFIED on disk evidence rather than re-run:

- All 8 sweep results files exist at `workspace/implementation/results.{1..8}.json`, and every round reports `total: 108, passed: 108, failed: 0, errors: 0` — a fully clean 8-round parallel stability sweep under `prd-bench-local-run --isolation per-test-server` (sweep completed ~08:49 UTC per file mtimes; `sweep.sh` is the script the subagent used).
- Route parity confirmed: the implementation registers 52 `(method, path)` route pairs, matching the 52 endpoints declared in `SCAFFOLD.yaml` §1.5.
- The verbatim iteration summary was lost with the interrupted run. Observable evidence of the iteration window: `implementation/routes_rides.py` and `implementation/routes_billing.py` were modified at ~08:35 UTC and `test_suite/test_11_ride_and_assignment_states.py`, `test_12_billing_and_driver_states.py`, `test_13_calculations_corner.py`, `test_14_validation_corner.py`, `test_15_rbac.py` at ~08:46–08:47 UTC — i.e. at least one diagnose→fix→rerun cycle occurred touching those files before the final clean sweep. The detailed deletions/fix list is unrecoverable; because Step 7 fixes demonstrably occurred, the Step 8 skip condition does NOT apply.

## Step 8: Finalize PRD — 2026-08-10T09:14:22.000Z

Produced `/home/ubuntu/github/CodingPRD/tasks/task_0975_concierge_senior_nonemergency_transport/workspace/PRD_FINALIZED.md` (copy of PRD.md with 14 inline line-level patches; no new sections).

**Line counts / delta:** PRD.md 346 lines / 57,709 chars; PRD_FINALIZED.md 346 lines / 61,270 chars; +0.0% lines, +6.2% chars (14 lines revised in place).

**Changes (one bullet per edit):**
- §3.3 — revise — pins the "ride's rate card" resolution chain (booking snapshots the ACTIVE card; series occurrences record the ACTIVE card covering their date if any; post-booking evaluations use the recorded card first even if retired, then ACTIVE-at-pickup, then latest-created covering card of the class; no resolvable card → cancellation/no-show fees zero and completion leaves `final_fare_cents` unset; completion re-records a newly resolved card) — implementation/billing.py:14-27, routes_rides.py:151-154, 347-356, domain.py:415-426.
- §3.4 — insert — ride `estimated_duration_minutes`/`estimated_distance_miles` must be non-negative, negative → `ERR_INVALID_REQUEST` — implementation/routes_rides.py:73-74 (via core.py:327-339).
- §3.4 — revise — generated occurrences snapshot client profile (`requires_wav`/`service_class`/`assist_level`), store the provisional quote when an ACTIVE card covers the date, log `CREATED`; generation is one shared routine (create/resume/edit/ops cycle) that produces nothing unless series and client are ACTIVE and skips dates already occupied by a non-CANCELLED ride of the series (no duplicates) — implementation/domain.py:357-366, 369-431; call sites routes_standing.py:132/236/276, billing.py:244-250.
- §3.5 — revise — dispatch gate-then-mutate: rejected attempts change nothing; gated attempts move the ride to `DISPATCHING` and increment `dispatch_round` before running the selector — implementation/routes_rides.py:244-255.
- §3.5 — revise — empty-pool outcome: ride left `DISPATCHING` with the round increment applied; neither an assignment nor log events are created — implementation/routes_rides.py:256-259.
- §3.6 — insert — per-event source-status legality: `EN_ROUTE` only from `ASSIGNED`, `ARRIVED` only from `EN_ROUTE`, `SERVICE_STARTED` only from `ARRIVED`, `COMPLETE` only from `IN_SERVICE`, `NO_SHOW` only from `ARRIVED`; `WAIT_STARTED`/`WAIT_ENDED` permitted from `ARRIVED` or `IN_SERVICE`, never change status, no nested/close-without-open — implementation/routes_rides.py:305-341.
- §3.6 — revise — completion requires non-negative integer `actual_distance_miles` (negative → `ERR_INVALID_REQUEST`) — implementation/routes_rides.py:286.
- §3.6 — revise — no-show fee uses the §3.3-resolved card (zero when none); strike rule is ">= 3 while client ACTIVE": a no-show for a non-ACTIVE client changes only the count — implementation/routes_rides.py:368-384.
- §3.6 — revise — ride log order: `occurred_at` asc, `created_at` asc, then recording order for remaining ties (all events share the frozen logical timestamp; insertion order decides) — implementation/routes_rides.py:403, domain.py:233-246.
- §3.7 — revise — cancellation fee bills against the ride's §3.3-resolved card (zero when none); `cancel_note` is carried on the appended `CANCELLED` event — implementation/routes_rides.py:222-235.
- §3.8 — revise — `CANCELLATION_FEE`/`NO_SHOW_FEE` lines: `unit_rate_cents` = resolved card's `minimum_charge_cents` (the recorded fee itself when no card resolves), `amount_cents` = the ride's recorded fee — implementation/billing.py:86-91.
- §3.8 — revise — voiding restores `credit_applied_cents` skipped when zero, leaving the client row untouched — implementation/routes_billing.py:179-183.
- §3.9 — revise — dispute endpoint gates per action before loading the invoice (BillingAdmin `RAISE` or non-BillingAdmin resolve → `ERR_UNAUTHORIZED_ROLE`); `RESOLVE_ACCEPT` `credit_cents` is optional, defaults to 0, negative → `ERR_INVALID_REQUEST`, bound check evaluated before the SoD check, zero credit leaves the client row untouched — implementation/routes_billing.py:189-203, 244-258.
- §3.9 — revise — refund check order pinned (`ERR_PAYMENT_NOT_REFUNDABLE` → non-positive `ERR_INVALID_REQUEST` → `ERR_REFUND_EXCEEDS_SETTLED`); reversal decrements `applications` entries in place and drops entries whose `applied_cents` reaches zero — implementation/routes_billing.py:353-366, billing.py:186-202.

**Per-edit pre-edit search log (subject / impl paths enumerated / wording adjustment):**
1. Rate-card resolution — enumerated `ride_rate_card` (billing.py:14-27) and all callers: routes_rides.py:151-154 (booking snapshot+quote), 222-224 (cancel), 347-356 (complete), 368-370 (no-show); billing.py:50, 80-91 (invoice lines); domain.py:415-426 (occurrences); `active_rate_card`/`any_rate_card_covering` (domain.py:57-76). (c) Scoped the "exactly one ACTIVE card must exist" claim to booking only, and added the series-occurrence "may carry none" clause, because the original universal wording would mis-describe cardless series rides and retired-snapshot reuse.
2. Ride-estimate validation — enumerated `field_int(..., minimum=0)` at routes_rides.py:73-74 and the shared validator core.py:327-339; confirmed no other ride-creation path. (c) Kept the clause scoped to one-off booking fields only (did not generalize to series/driver/rate fields, which live in untouched files).
3. Occurrence generation — enumerated `generate_occurrences` (domain.py:369-431), `ride_exists_on` (357-366), all four call sites (routes_standing.py:132, 236, 276; billing.py:247-250), and the guards at domain.py:371-375. (c) Added "produces nothing while the series is not ACTIVE or the client is not ACTIVE" so the dedup sentence isn't a false universal (PUT on a PAUSED series and cycles over suspended clients generate nothing).
4. Dispatch gates — enumerated all `dispatch_round` writes (routes_rides.py:135, 255, 264; routes_assignments.py:138; domain.py:322) and `DISPATCHING` transitions (routes_rides.py:254; routes_assignments.py:136; domain.py:320). (c) Confined the gate-then-increment claim to the dispatch endpoint; release/cascade increments remain covered by their own existing sentences.
5. Empty pool — enumerated dispatch early return (routes_rides.py:256-259) vs. event appends (277-278) which sit after the None-return. (c) Replaced "the ride stays DISPATCHING" (wrong for a first dispatch from SCHEDULED) with "left DISPATCHING with the round increment applied".
6. Execution-event legality — enumerated every branch of `execution_event` (routes_rides.py:305-373) plus `_open_wait_started_at`/`_service_started_at` lifecycle (routes_rides.py:149-150, 322-345; domain.py:409-410). (c) none needed after enumerating; the added table mirrors the branch guards exactly (tests only ever open waits from ARRIVED, but impl permits IN_SERVICE too — the wording allows both).
7. No-show strike — enumerated the only `no_show_count` writer (routes_rides.py:374-384), `suspend_client_cascade` (domain.py:299-305), and the manual suspend path (routes_clients.py:129-144). (c) Replaced "reaches exactly three" with "leaves an ACTIVE client's count at three or more" and added the non-ACTIVE clause, because impl re-fires after reinstatement (count 4+) and does not fire while SUSPENDED — both reachable states the old wording mis-described.
8. Log ordering — enumerated the feed sort (routes_rides.py:398-404) and the sole event writer `append_event` (domain.py:233-246, monotonic `_seq`). (c) none; "recording order" is well-defined for every append site.
9. Cancel fee/note — enumerated routes_rides.py:201-236 and `system_cancel_ride` (domain.py:287-296). (c) Scoped the note clause to caller-initiated cancels (system cancels append `CANCELLED` with no note).
10. Fee-line unit rates — enumerated `emit_lines_for_ride` (billing.py:65-91) and its caller `generate_invoice` (billing.py:95-129). (c) Included the no-card fallback ("the recorded fee itself") to keep the cardless-NO_SHOW invoice path (fee 0, still billed) consistent.
11. Void zero-credit skip — enumerated routes_billing.py:165-184 and all `credit_balance_cents` writers (billing.py:127/169/204, routes_billing.py:182/256). (c) Used the same "skipped when zero, leaving the client row untouched" phrasing the PRD already uses for generation, keeping the two symmetric.
12. Dispute gating — enumerated routes_billing.py:186-264 (action gate at 194-203 precedes `_invoice_or_404` at 204; credit bound at 246-247 precedes `_check_sod` at 248/260) and `_check_sod` (370-380). (c) Added "ahead of loading the invoice" and "evaluated before the segregation-of-duties check"; verified against §2.10's "SoD last" constraint (existence and dispute state still precede SoD — no conflict).
13. Refund checks/array shape — enumerated routes_billing.py:343-367 (check order) and `reverse_refund` (billing.py:173-211, in-place decrement at 200, zero-drop filter at 202, atomic pre-check at 178-185). (c) none.

**Deliberately not patched (considered, then excluded by hard scope):** the offer-timeout log event uses event type `EXPIRED`, which is absent from the §3.6 RideEvent vocabulary (billing.py:265) — but billing.py was not a Step-7-modified file and no test reads the log after a timeout, so it is not traceable to the Step 7 diff; same rationale for skipping release-path `responded_at` stamping (routes_assignments.py), the series rate-card gate date (routes_standing.py), and the double-`touch` version bump on the third no-show strike (unasserted artifact).

## Step 9: Complete PRD — 2026-08-10T09:30:00.000Z

Done. PRD_COMPLETED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_0975_concierge_senior_nonemergency_transport/workspace/PRD_COMPLETED.md` — 17 paragraphs revised in place, no lines added or removed, no new sections.

- Source: PRD_FINALIZED.md (346 lines, 61,270 chars) vs PRD_COMPLETED.md (346 lines, 64,003 chars) — char-delta +2,710; 17 paragraphs touched, all inline edits.
- Counts: ambiguity-pins 14, mismatch-revisions 3.

Changes:
- §2.1 — revise — mismatch — revoked/inactive FamilyMember rejected with `ERR_FAMILY_ACCESS_INSUFFICIENT` only on §2.6 guarded writes; portal reads fail ownership with `ERR_FORBIDDEN_OWNERSHIP` — core.py:273-280, routes_clients.py:26-35, routes_rides.py:38-48, routes_billing.py:27-36, routes_standing.py:143-148.
- §2.3 — insert — ambiguity — non-integer limit/offset, limit outside 1–100, or negative offset rejected with `ERR_INVALID_REQUEST` — core.py:189-216.
- §2.3 — insert — ambiguity — any timestamp-pinned ordering (list sorts, waterfall due_date, invoice-line emission, selector created_at tie-break) breaks full-key ties by record creation sequence — core.py:407-408, domain.py:217-224, billing.py:43,155.
- §2.8 — insert — ambiguity — operator configuration integers (rate-card tariff fields, `max_daily_service_minutes`, `billing_hold_limit_cents`) must be non-negative, else `ERR_INVALID_REQUEST` — routes_rates.py:23-32, routes_drivers.py:30, routes_clients.py:48,97.
- §3.1 — insert — ambiguity — status change on a `DEACTIVATED` client rejected with `ERR_INVALID_REQUEST` ahead of the version check; other-field edits still permitted — routes_clients.py:101-113.
- §3.1 — insert — ambiguity — revoking an already-`REVOKED` member succeeds as an idempotent no-op — routes_clients.py:219-221.
- §3.2 — insert — ambiguity — `renewal_of_doc_id` validated for existence only (`ERR_NOT_FOUND`); renewed doc's type/owner/status unchecked — routes_drivers.py:145-146.
- §3.4 — insert — ambiguity — `pickup_time_of_day_minutes` is an integer 0–1439, out-of-range `ERR_INVALID_REQUEST` — routes_standing.py:81-83,176.
- §3.4 — insert — mismatch — client-active gate and booker-attachment check fire before `linked_return_ride_id` is resolved, so either masks an unknown linked id (overrides §2.6 stage-6-before-7 for this field) — routes_rides.py:80-99, routes_standing.py:56-69.
- §3.4 — insert — ambiguity — series rate-card gate evaluated at the first upcoming cadence date (earliest series weekday from logical today within inclusive range, `starts_on` when none remains) — routes_standing.py:100-111.
- §3.4 — insert — ambiguity — generated occurrences copy `booked_by_family_member_id` from the series — domain.py:386.
- §3.4 — insert — ambiguity — editing an `ENDED` series is `ERR_STANDING_STATUS_INVALID`; an edited `PAUSED` series deletes future SCHEDULED occurrences (with their event-log entries) but regenerates nothing until resume — routes_standing.py:186-190,220-238.
- §3.5 — insert — ambiguity — declining stamps `responded_at` and `decline_reason`; the `DECLINED` event carries the decline reason as its note — routes_assignments.py:104-111.
- §3.5 — insert — ambiguity — driver release stamps `responded_at`; the `RELEASED` event carries the optional reason as its note — routes_assignments.py:129-142.
- §3.5 — insert — ambiguity — offer timeout logged as an `EXPIRED` event; global rule: `responded_at` stamped exactly when an assignment reaches `ACCEPTED`/`DECLINED`/`RELEASED` on any path (response, driver release, cancellation, suspension cascade), never on `EXPIRED` — billing.py:253-265, domain.py:254-270,308-326.
- §3.6 — revise — mismatch — RideEvent `event_type` vocabulary extended with `EXPIRED` (ops-cycle offer timeout emits it) — billing.py:265.
- §3.6 — insert — ambiguity — the striking third no-show applies the count increment and the suspension as two successive client mutations, advancing `version` twice — routes_rides.py:376-384.
- §3.7 — insert — ambiguity — `cancelled_by_role` is recorded as the caller's role — routes_rides.py:233.
- §3.8 — insert — ambiguity — `WAIT` line `quantity` is the billable wait minutes — billing.py:72-75.
- §3.10 — insert — ambiguity — ops-cycle response id sets list ids in creation order of the affected records — billing.py:229-287.
