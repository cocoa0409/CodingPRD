# Worklog — task_0960_ski_snowboard_tune_rental

## Step 9: Complete PRD — 2026-08-09T19:58:00.000Z

All edits applied cleanly — same line count (336), all changes are inline. Final report:

## Summary

**Source vs output:** `PRD.md` → `PRD_COMPLETED.md` (PRD_FINALIZED.md absent; started from PRD.md as instructed). Both 336 lines. Char delta: 53,639 → 56,396 (**+2,757 chars**). 20 paragraphs touched, all in-place inserts/revisions; no new sections.

**Counts:** 19 ambiguity-pins, 1 mismatch-revision.

**Changes:**

- §2.1 RBAC — insert — ambiguity — pinned that Customer callers on list endpoints get results scoped to their own resources (not rejected) — implementation/routes/reservations.py:71, tunes.py:93, demo.py:67,161, damage.py:73, pickup.py:128
- §2.3 Pagination — insert — ambiguity — non-numeric limit/offset → ERR_INVALID_REQUEST; out-of-range values clamped into range rather than rejected — implementation/envelope.py:49-60
- §2.7 Fleet occupancy — revise — mismatch — PRD's non-rentable enumeration omitted OUT, implying OUT units committable; impl rejects OUT too. Revised so only AVAILABLE/RESERVED are committable, RESERVED only via forced assignment — implementation/routes/reservations.py:300
- §2.9 OCC — insert — ambiguity — omitting the expected-version field entirely → ERR_INVALID_REQUEST, not ERR_STALE_VERSION — implementation/routes/tunes.py:131-134, leases.py:139-142
- §3.1 Customers — insert — ambiguity — duplicate email at registration → ERR_INVALID_REQUEST — implementation/routes/customers.py:24-25
- §3.1 Standing — insert — ambiguity — only INVOICED assessments count as unpaid; DISPUTED ones do not depress standing — implementation/services.py:184-196
- §3.2 Fleet — insert — ambiguity — purchase_price_cents and base_daily_rate_cents must be positive integers (ERR_INVALID_REQUEST) — implementation/routes/equipment.py:24-25
- §3.2 Retire — insert — ambiguity — non-AVAILABLE unit or assigned-line reference at retire → ERR_INVALID_STATE — implementation/routes/equipment.py:59-64
- §3.3 Add line — insert — ambiguity — adding a gear line requires parent reservation DRAFT/CONFIRMED, else ERR_INVALID_STATE — implementation/routes/reservations.py:90-92
- §3.3 Forced assign — insert — ambiguity — preferred unit failing gear/tier match → ERR_INVALID_REQUEST, and pinned check order gear/tier → DIN → status → occupancy — implementation/routes/reservations.py:293-306
- §3.3 Waitlist promotion — insert — ambiguity — promotion considers only QUEUED lines whose parent reservation is DRAFT/CONFIRMED and applies the full eligibility battery — implementation/services.py:136-152
- §3.4 Confirm — insert — ambiguity — assigned-line check runs before the deposit-floor check — implementation/routes/reservations.py:124-129
- §3.4 Cancel — insert — ambiguity — cancellation also moves still-QUEUED lines to RELEASED — implementation/routes/reservations.py:148-150
- §3.4 Return — insert — ambiguity — return moves each assigned line to a RETURNED line status — implementation/routes/reservations.py:205
- §3.4 Return — insert — ambiguity — accrued_rental_days increment clamped at zero — implementation/routes/reservations.py:209
- §3.5 Capacity — insert — ambiguity — rush pool exceeding base or negative pool sizes → ERR_INVALID_REQUEST — implementation/routes/capacity.py:17-21
- §3.6 Reinstate — insert — ambiguity — reinstatement while junior still BARRED refused with ERR_INVALID_STATE — implementation/routes/leases.py:191-193
- §3.7 Purchase order — insert — ambiguity — a named demo_credit_id applies that credit alone, not the full eligible pool — implementation/routes/demo.py:121-124
- §3.7 Order cancel — insert — ambiguity — freeing the unit on cancel triggers waitlist promotion like a released rental line — implementation/routes/demo.py:219-222
- §3.8 Damage assessment — insert — ambiguity — remainder_due_cents initialized to full charge_cents at creation — implementation/routes/damage.py:54
- §3.9 Pickup bookings — insert — ambiguity — complete/cancel against a closed window → ERR_INVALID_STATE; window closure resets booked_count to zero — implementation/routes/pickup.py:151-153,167-169, services.py:315

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_0960_ski_snowboard_tune_rental/workspace/PRD_COMPLETED.md`

## Step 8: Finalize PRD — 2026-08-09T19:57:30.000Z

SKIPPED per the skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced.

## Step 7: Run tests and iterate — 2026-08-09T19:57:00.000Z

All 8 parallel rounds completed with 86/86 tests passing in every round — no failures, no flakiness signal. Exiting per protocol.

Summary:
- Iterations run: 1 (8-round parallel sweep, all rounds run to completion)
- Tests deleted: none
- Fixes applied to `test_helpers/`: none
- Fixes applied to `implementation/`: none
- Result: round 1-8 all report `passed == total` (86/86) in `/home/ubuntu/github/CodingPRD/tasks/task_0960_ski_snowboard_tune_rental/workspace/implementation/results.{1..8}.json`. The implementation and test artifact are stable under the 8x concurrent per-test-server sweep; no diagnostic work was required.

## Step 5: Generate unit tests — 2026-08-09T19:50:00.000Z

Generation complete. All stage checks pass.

## Summary

**Files written**

`test_helpers/` (9 files):
- `types.py` — 15 status/role enums + 13 entity TypedDicts (all entities are common-fields: id, created_at, updated_at, version)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (54 methods incl. `set_clock`), plus module-level `api_client`
- `api_errors.py` — `ApiErrorId` enum (31 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` shape validators + `assert_deposit_conservation` invariant
- `factories.py` — payload factories for all 12 creatable resources (input fields only, unique emails/labels via counter)
- `constants.py` — thresholds (discount tiers, DIN band, service prices/labor, severity pcts, buyout/depreciation rates, watch threshold, clock startup default)
- `test_users.py` — shared `TEST_USERS` for opaque roles + `make_customer_headers(user_id)` entity-backed builder (used for every ownership-gated Customer call)
- `fixtures.py` — composite builders: `make_customer/junior/guardian`, `make_equipment_item` (+ JUNIOR/DEMO variants), `setup_assigned/confirmed/picked_up/returned_reservation`, `setup_approved_ticket`, `setup_ticket_in_quality_check`, `setup_active_lease`, `setup_suspended_lease_via_total_loss`, `make_demo_credit`, pickup window/booking helpers — all built from PRD endpoints via `get_success_data`
- `__init__.py` — barrel export of framework generics + PRD-specific code

`test_suite/` (12 files): `conftest.py` + `test_01_customers_and_envelope.py`, `test_02_fleet_pagination_and_selector.py`, `test_03_reservation_lifecycle.py`, `test_04_assignment_occupancy_and_waitlist.py`, `test_05_rental_pricing_and_fitment.py`, `test_06_tune_tickets.py`, `test_07_season_leases.py`, `test_08_damage_standing_and_deposits.py`, `test_09_demo_and_purchase.py`, `test_10_pickup_logistics.py`, `test_11_rbac_and_auth.py`

**Test counts**
- Queue A (Difficulty): **36 tests** — all 18 instances covered by exactly 2 tests each
- Queue B (Corner): **50 tests** — all 49 non-stub instances covered (≥1 each); the 7 `excluded_because` stubs were not translated and their difficulty-instance cross-references all resolve
- Total: **86 tests**

**Instances skipped**: none. Every instance passed the PRD-first two-condition filter (the PRD covers every asserted rule verbatim, including the §2.10 precedence ladder for both priority-pair instances). One derivability accommodation: `expires_at`/`promised_at` are asserted by timestamp-prefix comparison (e.g. `startswith("2027-03-01T00:00:00")`) rather than exact-string equality, since PRD §2.4 permits a 3-fractional-digit serialization.

**Check results**
- `py_compile` on all files: OK
- `pyflakes`: clean (only intentional barrel-export re-export notices in `__init__.py`, which carry `# noqa` and are by design)
- pytest collection with task dir on PYTHONPATH: **86 tests collected**, no import errors
- Tag audit: 86/86 tests carry exactly one `Design: Difficulty/...` or `Design: Corner/...` line; all tags resolve to real instance names; no stub pointers broken
- PRD verbatim-citation pass: 115 quoted citation segments checked, 0 grep failures
- No "scaffold" references anywhere in generated code

## Step 6: Generate implementation — 2026-08-09T19:50:00.000Z

Implementation complete. Summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_0960_ski_snowboard_tune_rental/workspace/implementation/`)

- `start.sh` — executable launcher; guarded `pip install` (no-op once Flask is importable, per the per-test-reboot contention note), then `exec python3 app.py` in the foreground
- `requirements.txt` — flask
- `app.py` — Flask app factory, error handlers (envelope-shaped errors for `ApiError`, HTTP 404/405, generic 500), `before_request` lazy clock sweeps, binds `0.0.0.0:$PORT` (default 10000)
- `store.py` — in-memory dict store (12 entity collections keyed by id), logical clock defaulting to exactly `2026-05-01T00:00:00Z`, ISO-8601 3-fractional-digit timestamps, common fields (`id`/`created_at`/`updated_at`/`version`), `touch()` bumps version +1 per mutation. No seeding anywhere — store starts empty on every boot
- `errors.py` — `ApiError` + the full 31-entry error catalog with exact IDs/HTTP statuses
- `envelope.py` — exact envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; error body `error_id`/`message`), `limit`/`offset` pagination (default 10, min 1, max 100) with `total_count`/`has_more` in meta
- `auth.py` — `X-User-ID`/`X-User-Role` auth (`ERR_UNAUTHENTICATED`/`ERR_UNAUTHORIZED`), Customer ownership chain checks (`ERR_FORBIDDEN_OWNERSHIP`)
- `validate.py` — field/enum/date/time validators (`ERR_INVALID_REQUEST`), `get_or_404`
- `services.py` — all 9 scaffold calculations in Decimal with ROUND_HALF_UP (fitment DIN with 0.25-step rounding, rental provisional/final per-line rounding, tune quote rush-then-junior multiplier order, damage nested-min depreciation, deposit waterfall, demo pricing with 30% cap, lease buyout dual variants, pickup posture, customer standing), occupancy windows with the 1-free-day rule, selector policy + waitlist promotion cascade, standing→lease-suspension cascade, clock sweeps (overdue/credit-expiry/window-close+no-show)
- `routes/` — 10 blueprint modules: customers, equipment, reservations (+reservation-items), tunes, leases, demo (demo-credits + purchase-orders), damage, pickup (windows + bookings), capacity, clock

## Endpoint count

All **64 endpoints** from the scaffold §1.5 table are implemented (including `POST /_clock/set_current_utc`).

## Verification

Two assertion-based end-to-end suites were run against fresh boots, covering: DIN fitment math (6.25 verified by hand), quote/deposit minimum, late-return final charge with 1.5x punitive term, overdue sweep, deposit waterfall conservation, TOTAL_LOSS → BARRED → lease suspension → pay → reinstate, dispute/resolve UPHELD with adjusted charge (capture delta compensation) and WAIVED, junior lease age/guardian rules, swap OCC (`ERR_STALE_VERSION` 412), buyout variants (66522 vs 55200 verified by hand), demo credit 90-day expiry and 30% cap pricing, half-open window overlap/adjacency, window FULL boundary and NO_SHOW sweep, waitlist promotion on release, rush capacity exact-fit/exceeded, rework limit, capacity-full at qc-fail, pagination envelope, RBAC and ownership scoping. All assertions passed. One real bug was found and fixed during testing (invoice's standing recompute ran before the assessment flipped to INVOICED).

## start.sh contract confirmation

Confirmed by direct invocation: `bash start.sh` runs the server in the foreground via `exec`, bound to `0.0.0.0` on `$PORT` (tested on 18713), responding within seconds, with an empty store and the default logical clock on every fresh process — safe for `--isolation per-test-server` reboots.

## Step 4: Generate PRD — 2026-08-09T19:28:00.000Z

PRD generation complete. All audits pass.

## Summary

**File written:** `/home/ubuntu/github/CodingPRD/tasks/task_0960_ski_snowboard_tune_rental/workspace/PRD.md` — 336 lines.

**Section coverage:**
- §1 Introduction — 3 paragraphs (fleet-contention business angle, cascade/immediacy design ideas, URL mount)
- §2 Global Specifications — 11 subsections: 2.1 RBAC (all 4 roles, `identity:` translated for each; `Customer` entity-backed, others opaque), 2.2 Response Structure (verbatim fixed block), 2.3 Pagination (limit 10/1/100, offset 0, created_at ascending), 2.4 Common Resource Properties (UUID id, 3-fractional-digit timestamps, version starts at 1), 2.5 Logical Clock (startup default `2026-05-01T00:00:00Z`, sweep behavior), 2.6 Cents & Rounding (integer cents, round-half-up, per-line-before-sum and multipliers-before-round pinned orders, DIN 0.25 steps), 2.7 Fleet Occupancy (closed intervals, one-free-day gap, non-rentable statuses, terminal lockdown), 2.8 Deposit Waterfall (conservation invariant, created_at-ordered capture, estimate-vs-final variants), 2.9 OCC (exactly two guarded writes, `expected_tune_ticket_version` / `expected_season_lease_version`, `ERR_STALE_VERSION` 412), 2.10 Validation Precedence ladder, 2.11 Cascading consistency
- §3 Business Logic — 9 subsections (customers/standing, fleet lifecycle, reservation booking + DIN fitment + selector, confirm-to-close money cycle, tune workshop + capacity, junior season leases, demo/purchase, damage cascade, slope-side logistics); all rules scattered with state-pair framing, no paths
- §4 Endpoint table — 4 columns only, all 66 endpoints with exact roles
- §5 Error catalogue — 2 columns only, all 31 errors

**Coverage audit results:**
```
Field coverage check:
- entities[].fields: 85 required, 85 present, 0 missing
- endpoints[].request_body: 54 required, 54 present, 0 missing
- endpoints[].query_params: 17 required, 17 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 31 checked, 31 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (endpoint + occ field + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 10 machines / all transitions checked, fully expressed (preconditions + error ids + side effects), 0 missing
- calculations[]: 10 checked, 10 fully expressed (formulas, constants, precision, dual variants), 0 missing
- validations[] conditions: 31 checked, 31 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (multi-endpoint scopes enumerated, e.g. capacity gate at start/qc-fail, junior-age at create/activate), 0 missing
- entities[].fields[] structured content: defaults/initials/computed semantics reconstructible, 0 missing
- sibling-branch symmetry: inspect outcomes, resolve UPHELD/WAIVED, provisional/final rental variants, straight-line/usage buyouts, estimate/final deposit variants all at equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 202
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: all 31 error IDs appear in §2/§3 prose; all 73 enum/state values (including `PASS`/`NEEDS_TUNE`/`DAMAGED`, `UPHELD`/`WAIVED`, `TYPE_1`–`TYPE_3`) appear as exact strings. The withheld difficulty/corner index files were not opened or referenced.

## Step 3: Copy shared files — 2026-08-09T19:19:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0960_ski_snowboard_tune_rental/workspace/INSTRUCTION.md` (1424 bytes).

## Step 2: Generate scaffold — 2026-08-09T19:18:00.000Z

All three artifacts are written and the scaffold lints clean. Summary:

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_0960_ski_snowboard_tune_rental/SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_0960_ski_snowboard_tune_rental/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_0960_ski_snowboard_tune_rental/SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

## Counts
- **Entities: 12** (Customer, EquipmentItem, Reservation, ReservationItem, TuneTicket, SeasonLease, DemoCredit, PurchaseOrder, DamageAssessment, PickupWindow, PickupBooking, ShopDayCapacity)
- **State machines: 10** (Reservation is parallel payment×fulfillment axes; TuneTicket and DamageAssessment are cyclic rework/dispute loops; PickupWindow is posture-derived)
- **Calculations: 10** (fitment DIN, dual-variant rental charge, tune quote, nested-min damage charge, deposit waterfall, demo-upgrade pricing, dual-variant lease buyout, window posture, standing threshold, turnaround/rush scheduling)
- **Validations: 31** ordered priorities (auth → ownership → existence → OCC 412 → state → temporal → constraint → referential → fiscal)
- **Endpoints: 66** (flat `/shop/*` space + `/_clock/set_current_utc` with pinned default 2026-05-01T00:00:00Z)
- **Errors: 31**, every one exercised by at least one test recipe
- **Roles: 4** (Customer entity-backed; FrontDesk/Technician peers; Manager hierarchical override)
- **Concurrency rules: 2** (OCC on TuneTicket quote-approval and SeasonLease swap — both supersede/approve-pinning true races)

## Difficulty design (beyond-Expert)
Archetype quota/allocation × temporal windowing, with OCC, cascades, dual-variant calcs, threshold triggers, and selector-policy layers. All 9 rules × 2 instances = **18 instances**, each with replayable structured recipes and pre-computed literal asserts (e.g., per-line rounding order 63033 vs 63032; DIN branch divergence 5.75 vs 6.5; buyout variants 24000 vs 12000; depth-3 cascade invoice → deposit capture → standing BARRED → lease SUSPENDED; closed-interval+1-day-gap vs half-open-adjacency overlap semantics; deposit conservation 5000 = 2000 + 3000).

## Corner design
**49 instances scanned by lint** (42 active recipes + 7 `excluded_because` stubs citing §1.8 instances): entity creation/defaults/system-field-immunity/not-found/pagination, initial/terminal/invalid/auto transitions (overdue, credit expiry at inclusive boundary, no-show on window close), calculation constants/boundaries (7-day discount tier, depreciation floor, credit cap, WATCH at exactly 3 late returns), every error's trigger path, RBAC denials + ownership + Manager override, both OCC stale-version paths, selector created_at ordering, cancel-driven promotion cascade, and immediate-consistency envelope checks.

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (563 calls scanned, 0 violations). No forbidden race vocabulary; no duplicate instance names across the two design files. No sibling task directory was inspected.

## Step 1: Create task directory — 2026-08-09T00:00:00.000Z

Task directory `tasks/task_0960_ski_snowboard_tune_rental/` and its `workspace/` subdirectory were pre-assigned and already exist (headless run; Step 1 auto-index scan skipped per instructions). Verified both exist on disk.
