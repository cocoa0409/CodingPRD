# Worklog — task_1180_residential_yard_waste_composting_program

## Step 1: Create Task Directory — 2026-08-11T12:06:00.000Z

Pre-assigned output folder `tasks/task_1180_residential_yard_waste_composting_program` with `workspace/` subdirectory already exists (auto-index scan skipped per instructions). Step 1 treated as done.

## Step 2: Generate Scaffold — 2026-08-11T13:26:00.000Z

All three scaffold artifacts generated and verified for task 1180 (Residential Yard Waste & Composting Program), written to `/home/ubuntu/github/CodingPRD/tasks/task_1180_residential_yard_waste_composting_program/`. No sibling task directories were inspected; the design was derived purely from the scenario text plus the skill spec.

**Design summary** (difficulty: harder-than-expert — flat topology, cyclic state machines, segregation-of-duties RBAC, logical-clock-driven seasonal windows):

- **SCAFFOLD.yaml** — 15 entities (ServiceZone, Household, Subscription, Cart, CollectionRoute, PickupTicket, ContaminationInspection, SurgeEvent, SurgeBooking, ProcessingFacility, FacilityDelivery, CompostGivebackEvent, CompostClaim, ServiceCredit, OutreachCampaign), **62 endpoints**, **13 state machines** (incl. cyclic Subscription ACTIVE↔SUSPENDED, PickupTicket SCHEDULED↔MISSED_REPORTED, OutreachCampaign ACTIVE↔PAUSED, clock-derived zone/event statuses), **9 calculation rules** (dual-variant opt-in vs universal fee; prorated vs flat missed-pickup credit; pinned per-pickup rounding compost entitlement; strike threshold; route stop/tonnage capacity; waitlist selector; credit-ledger balance; campaign spend), **12 ordered validation priorities**, **37 error codes** (all referenced/triggerable), **8 roles**, **2 OCC concurrency rules** (subscription-create on Household.version, surge-booking on SurgeEvent.version), `POST /_clock/set_current_utc` with pinned default 2026-05-01T00:00:00Z. All numeric fixtures pre-computed (e.g., prorated base 7555, credit 444 vs 500, entitlement 5.01 vs 5.00 rounding-order divergence, inventory floor(10000×0.025)=250).
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** — single key `scaffold_difficulty_design`, **18 instances (2 per each of the 9 rules)**, each with structured setup_api_calls/trigger/assert and literal-computed expected values.
- **SCAFFOLD_CORNER_DESIGN.yaml** — single key `scaffold_corner_design`, **63 active instances + 18 `excluded_because` stubs** across all nine guide sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_layers, consistency_model).

**Verification**: `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (726 calls scanned). Custom audit additionally confirmed: file split honored, all `grounds:` references resolve, no unbound `${var}` placeholders (including asserts), zero forbidden concurrency vocabulary, and instance names unique across both design files (99 total).

## Step 3: Copy Shared Files — 2026-08-11T13:27:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1180_residential_yard_waste_composting_program/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-11T13:36:00.000Z

The PRD was generated and written to `/home/ubuntu/github/CodingPRD/tasks/task_1180_residential_yard_waste_composting_program/workspace/PRD.md`. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) and all sibling task directories were never opened.

## PRD section list

- **§1. Introduction** — 2 paragraphs (municipal operations pain points + segregation-of-duties/logical-clock framing)
- **§2. Global Specifications & System-Wide Principles**
  - 2.1 User and Role-Based Access Control (8 roles; `Resident` entity-backed by `Household`, all others opaque; per-role identity prose)
  - 2.2 API Response Structure (fixed block emitted verbatim, including `req_RANDOMALPHANUM123456` and `"data": { }`)
  - 2.3 Pagination (`limit` default 10 / min 1 / max 100, `offset` default 0, `created_at` ascending, meta fields)
  - 2.4 The Logical Clock and Season-Derived Status (startup default `2026-05-01T00:00:00Z`; derived zone/surge/giveback statuses; lazy re-evaluation)
  - 2.5 Common Resource Properties (UUID `id`, `created_at`/`updated_at` 3-fractional-digit ISO 8601, `version`; inspections and service credits carry only `id` + `created_at`)
  - 2.6 Optimistic Concurrency Control (both OCC rules with `expected_household_version` / `expected_surge_event_version` → `ERR_STALE_VERSION` 412, stale-read framing, no race language)
  - 2.7 Monetary Precision, Yield Ratios, and Rounding (integer cents, floor proration, 0.025 gal/lb, per-pickup round-half-up)
  - 2.8 Validation Pipeline and Error Precedence (the 12-priority ordered pipeline, first-failure-wins, each step paired with its error IDs)
  - 2.9 Resource Addressing and Flat Topology (left-to-right 404 resolution)
  - 2.10 Immediate Consistency and Cascading Side Effects
- **§3. Business Logic & Workflows** — 9 subsections: 3.1 Zoning & Household Registration · 3.2 Season Signup & Subscription Billing (tiered fee, proration, pay/top-up, cancel cascades) · 3.3 Carts & Fee Accrual (size surcharges $15/$30, $25 extra-cart fee, retrieval) · 3.4 Routes, Scheduling & Pickup Day (half-open windows, 200 lb/ticket capacity checks) · 3.5 Contamination Inspection & the Strike Regime (threshold-at-or-above suspension, 2000-cent surcharge, cure) · 3.6 Missed Pickups & the Service Credit Ledger (validate → approve segregation of duties, oldest-first credit application) · 3.7 Surge Events & Slot Allocation (waitlist promotion ordering) · 3.8 Facility Receiving, Compost Inventory & Giveback (buffered bay windows, three-gate accept, pinned 2dp rounding with the 133+67 lb worked example, quota ladder in fixed order) · 3.9 Outreach Campaigns
- **§4. Endpoint Definitions** — 62-row table, 4 columns only (Method / Path / Description / Authorized Roles)
- **§5. Error Code Catalogue** — 39-row table, 2 columns only (no trigger conditions)

## Hard Contract reports

```
Field coverage check:
- entities[].fields + endpoints input/query/path identifiers: 85 required, 85 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority ordering: 12 steps expressed as an explicit ordered pipeline
- concurrency_rules[] OCC rejections: 2/2 expressed (endpoint + expected_*_version field + ERR_STALE_VERSION/412)
- state_machines[].transitions: all transitions, preconditions, and side effects expressed (incl. ERR_PAYMENT_NOT_REQUIRED, which is state-machine-only and therefore intentionally absent from §5)
- calculations[]: 9/9 expressed in precise prose (no pseudocode operators, no fuzzy words; reconstruction-safe)
- validations[] conditions: all matchable to error IDs in §2.8/§3 prose; all 39 scaffold error IDs mentioned before §4
- endpoints[].side_effects / applies_to: all expressed (receive accept gates, route-PUBLISHED trio, fiscal gates, cascades)
- entities[].fields[] structured content: defaults, derived statuses, enum sets, snapshot pinning all reconstructible
- sibling-branch symmetry: cancel/expiry/campaign terminal branches and accept/reject rendered with equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 475
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Metrics

- **Lines:** 315
- **Words:** 6,969
- **File written:** `/home/ubuntu/github/CodingPRD/tasks/task_1180_residential_yard_waste_composting_program/workspace/PRD.md` — confirmed on disk, ending at §5 with no audit footer.

## Step 5: Generate Unit Tests — 2026-08-11T14:22:00.000Z

Done. Summary of the generation run:

## Files written

**test_helpers/** (8 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1180_residential_yard_waste_composting_program/test_helpers/`):
- `types.py` — 15 entity TypedDicts + 20 enums; `ContaminationInspection` and `ServiceCredit` correctly omit `updated_at`/`version` (immutable evidentiary records per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with 44 methods covering every PRD §4 endpoint including `/_clock/set_current_utc`
- `api_errors.py` — 41 `ApiErrorId` members; 40 HTTP statuses from PRD §5 registered via `set_error_http_status_map` (`ERR_PAYMENT_NOT_REQUIRED` named in PRD §3.2 prose but absent from the §5 catalogue, so it is an enum member with no registered status)
- `assertions.py` — 15 per-entity assertions + slot/ledger invariant checkers
- `factories.py`, `constants.py` (fee schedule 1500/3000/2500, 2000 reinstatement surcharge, 0.025 gal/lb, 200 lbs avg, 27-week season), `test_users.py` (shared constants + `make_resident_headers(household_id)` for the entity-backed Resident role)
- `fixtures.py` — composite builders: `setup_active_household[_with_route]`, `setup_suspended_subscription`, `setup_pending_credit`, `setup_open_surge_event`, `setup_giveback_scenario`, `setup_facility_with_route`, plus per-action helpers that always thread fresh OCC version reads

**test_suite/** (11 files): `conftest.py` + `test_01_zones_households_subscriptions.py` (17), `test_02_carts_and_cart_fees.py` (5), `test_03_routes_and_pickup_tickets.py` (12), `test_04_contamination_and_strikes.py` (12), `test_05_missed_pickups_and_service_credits.py` (9), `test_06_surge_events_and_bookings.py` (13), `test_07_facilities_and_deliveries.py` (8), `test_08_compost_giveback.py` (9), `test_09_outreach_campaigns.py` (2), `test_10_security_envelope_and_rbac.py` (10).

## Counts
- **Total: 99 tests** (pytest collects 99/99)
- **Queue A (Difficulty): 36 tests** — all 18 instances with exactly 2 tests each
- **Queue B (Corner): 63 tests** — all 63 non-stub instances with 1 test each
- **Skipped: 0 instances** — every non-stub instance passed the PRD-first two-condition filter; the 18 `excluded_because:` stubs were not translated, and all 18 stub cross-references resolve to real difficulty instances

## Notable adjudications
- Several recipes create carts on `PENDING_PAYMENT` opt-in subscriptions, but PRD §3.3 verbatim requires the subscription to be `ACTIVE` for cart requests. Where a recipe's asserted literals depended on it, I reordered setup to PRD-legal (pay base fee first, then add carts) while preserving every asserted literal (e.g. suspend/cure cycle still ends at `paid_cents == 15500`, `surcharge_cents == 4000`); the opt-in `PENDING_PAYMENT` lifecycle half of the fee-variant instance is asserted at creation time (no carts) where the PRD pins it.
- Priority-pair tests were kept because PRD §2.8 ("the first failing check wins" with numbered steps) and §3.8 ("three gates in this order") state the precedence explicitly.

## Stage-2 lint/tag audit verdict
- **PASS** — every test docstring ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line; all 99 tags resolve to real instances; zero untagged/dual-tagged tests
- **Verbatim citation check PASS** — all 131 long (≥8-word) quoted spans match PRD.md literally after whitespace normalization
- No `skip`/`skipif`/`xfail` markers, no scaffold references in generated code, all modules compile and import cleanly

Orchestrator verification: pytest --collect-only → 99 tests collected; all 8 test_helpers files + 11 test_suite files present on disk.

## Step 6: Generate Implementation — 2026-08-11T14:22:00.000Z

Implementation complete. Summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1180_residential_yard_waste_composting_program/workspace/implementation/`)

| File | Bytes |
|---|---|
| start.sh | 263 |
| requirements.txt | 11 |
| app.py | 2125 |
| db.py | 2500 |
| errors.py | 3270 |
| response.py | 2339 |
| middleware.py | 929 |
| services/core.py | 19455 |
| services/validate.py | 2514 |
| routes/zones.py | 4445 |
| routes/households.py | 2084 |
| routes/subscriptions.py | 8824 |
| routes/carts.py | 4177 |
| routes/routes.py | 4054 |
| routes/tickets.py | 8375 |
| routes/inspections.py | 4440 |
| routes/surge.py | 8308 |
| routes/facilities.py | 9727 |
| routes/compost.py | 7502 |
| routes/credits.py | 2743 |
| routes/campaigns.py | 5311 |
| routes/clock.py | 753 |
| routes/__init__.py, services/__init__.py | 0 |

## Endpoint count
**62 spec endpoints registered** (verified against SCAFFOLD.yaml §1.5 — the only extra rule is Flask's built-in `/static/<path:filename>` handler, which is inert). All 62 (method, path) pairs from the endpoint table are present: zones (4), households (3), subscriptions (6), carts (4), routes (4), pickup-tickets (6), contamination-inspections (3), surge-events (3), surge-bookings (4), facilities (4), facility-deliveries (4), giveback-events (3), compost-claims (4), service-credits (4), outreach-campaigns (5), `_clock/set_current_utc` (1).

## Key design points
- **In-memory only** — module-level `Store` in `db.py` with plain dicts; empty at every boot, no seeding, no disk persistence.
- **Logical clock** defaults to `2026-05-01T00:00:00Z`; set via `POST /_clock/set_current_utc`. All clock-derived statuses (zone/surge/giveback) and system transitions (expiry, archival, cart retrieval, no-show, campaign completion) run lazily via `reconcile_all()` in `before_request`.
- **Envelope** matches SCAFFOLD §1.0 exactly: `meta.api_request_id` / `api_request_timestamp`, `response_type`, `data`; list responses add `limit`/`offset`/`total_count`/`has_more` in `meta`.
- **Auth**: `X-User-ID` + `X-User-Role` headers; eight roles; Resident identity is the Household id; opaque ids for operator roles.
- **Validation pipeline** follows PRD §2.8 ordering: auth → role → resident-ownership → path existence → request shape → body FK existence → state → safety → uniqueness/capacity/quota → temporal → referential → fiscal.
- **Calculations** use `Decimal` with `ROUND_HALF_UP` for compost entitlement (per-pickup 2dp rounding, pinned mode-b order); integer floor division for proration, credit amounts, giveback inventory.
- **OCC** on `expected_household_version` (POST /subscriptions) and `expected_surge_event_version` (POST /surge-bookings) → `ERR_STALE_VERSION` (412).
- **Segregation of duties** enforced on credit approval (`ERR_SEGREGATION_OF_DUTIES`).
- **Light records** (inspection, credit) omit `updated_at`/`version` per PRD §2.5.
- **Cascades** implemented: suspension (surcharge + skip future tickets), cancel (bookings + promotion, carts, future tickets), zone expiry, route archival, cart retrieval, no-show marking, campaign completion.

## Smoke test
- `python3 -c "import app"` — clean import, 63 routes enumerated.
- `PORT=18099 bash start.sh` — booted in foreground, bound 0.0.0.0, responded within 2s.
- `POST /service-zones` as ProgramAdmin → HTTP 201, correct envelope, zone `IN_SEASON` under the default clock.
- `GET /service-zones/nope` → HTTP 404 `ERR_ZONE_NOT_FOUND` in the error envelope.
- `GET /service-zones` without headers → HTTP 401 `ERR_UNAUTHENTICATED`.
- Server killed cleanly after test.

Orchestrator pre-sweep route-parity check: independent YAML-vs-Flask comparison → spec=62 impl=62 missing=0 extra=0. PASS.

## Step 7: Run Tests and Iterate — 2026-08-11T14:48:00.000Z

All 8 parallel rounds pass 99/99 with all results files verified non-empty and fully green.

## Summary

**Iterations run: 3 sweeps (8 parallel rounds each)**
- Sweep 1: 89/99 in all 8 rounds — 10 stable failures, zero flakiness.
- Sweep 2 (after test-side cart/season fixes): 98/99 in all 8 rounds — 1 stable failure.
- Sweep 3 (after implementation strike-counter fix): 99/99 in all 8 rounds. Clean.

**Tests deleted: none.** Every failing test traced to verbatim PRD prose; no PRD-silence or unique-derivability deletions were warranted.

**Fixes applied to `test_helpers/` and `test_suite/` (test bugs, STEP 2):**
- `test_helpers/factories.py` — `create_cart_payload` defaulted `size_gallons="64"` (string); PRD §3.3 declares the tier as `35`, `64`, or `96` (bare integer literals) and §2.8 step 5 requires correct types. Changed default to int `64`.
- `test_helpers/fixtures.py` — `create_cart` default `size_gallons="64"` → `64`.
- `test_helpers/assertions.py` — `assert_cart` accepted string sizes; tightened to int-only membership `(35, 64, 96)`.
- Call sites sending string sizes converted to ints: `test_01` (4 calls), `test_02` (7 calls, incl. the invalid-enum case `"50"` → `50` so it exercises the enum-member rule, not the type check), `test_04` (`with_cart_size=64` ×2), `test_05` (inline payload `64`).
- `test_helpers/fixtures.py` — `setup_open_surge_event` gained `**zone_overrides` passthrough to `create_zone`.
- `test_suite/test_06_surge_events_and_bookings.py` — `test_immediate_read_after_write_consistency` booked a 2027-01-03 HOLIDAY_TREE event at clock 2026-12-26 against a zone whose season ended 2026-10-31; per PRD §3.1 the subscription is EXPIRED by then and §3.7 requires an ACTIVE subscription, so the PRD-faithful implementation correctly returned `ERR_SUBSCRIPTION_NOT_ACTIVE`. Passed `season_end_date="2027-02-28"` so the season covers the booking window, preserving the test's §2.10 immediate-consistency assertion.

**Fixes applied to `implementation/` (STEP 3):**
- `workspace/implementation/routes/inspections.py` (`create_inspection`) — strikes were recomputed from the inspection log (`recompute_strikes`), which undoes the cure's reset: after a cure, the first new TAGGED_REJECTED counted 3 old + 1 new = 4, instantly re-suspending and skipping the remaining fresh tickets (causing `ERR_TICKET_NOT_SCHEDULED` on their inspections). PRD §3.5's "A successful cure resets `strikes_this_season` to zero … The cycle from `ACTIVE` to `SUSPENDED` and back is repeatable within a season" requires a stored counter. Changed to `sub["strikes_this_season"] += 1`; the cure's existing `= 0` reset now holds.
- `workspace/implementation/services/core.py` — `recompute_strikes` reduced to a read-only accessor with a deprecation note (no callers remain).

Orchestrator verification of final sweep artifacts: results.1.json … results.8.json all present, non-empty, each `passed=99 total=99 failed=0`.

## Step 8: Finalize PRD — 2026-08-11T14:55:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1180_residential_yard_waste_composting_program/workspace/PRD_FINALIZED.md` is written with exactly one revision.

**Line counts:** PRD.md 315 lines, PRD_FINALIZED.md 315 lines — 0.0% line-count delta (one in-place sentence revision on line 164; no sections added or removed).

**Changes (one bullet per change):**
- §3.5 — revise — replaced the derived-count definition of `strikes_this_season` ("the count of `TAGGED_REJECTED` inspections across that subscription's tickets") with pinned stored-counter semantics: stored on the subscription, starts at zero at creation, +1 per `TAGGED_REJECTED` inspection, `PASSED`/`TAGGED_WARNING` never increment, never recomputed from the inspection log, and only a successful cure returns it to zero (so pre-cure strikes don't count toward the next suspension). The threshold sentence ("reaches `max_strikes_per_season` while `ACTIVE` …") and the rest of the paragraph are verbatim — `workspace/implementation/routes/inspections.py:75-84`, `workspace/implementation/routes/subscriptions.py:83` and `:226`, `workspace/implementation/services/core.py:224-228`.

**Step_7_diff items deliberately not patched (PRD already determines behavior — pure test bugs):**
- Cart `size_gallons` int type (factories/fixtures/assertions/call-site fixes): PRD §3.3's bare integer literals (`35`, `64`, `96`) plus §2.8 step 5 ("types are correct, enum members are valid") already pin the JSON-integer requirement that `routes/carts.py:27-30` + `services/validate.py:42-46` (`req_int`, rejects bools/strings) implement. Prose kept verbatim.
- `setup_open_surge_event **zone_overrides`: fixture plumbing only, no observable behavior.
- test_06 `season_end_date="2027-02-28"`: PRD §3.1 (subscriptions go `EXPIRED` past `season_end_date`) and §3.7 (booking requires an `ACTIVE` subscription → `ERR_SUBSCRIPTION_NOT_ACTIVE`, impl `routes/surge.py:129-133`) already determined the rejection; the test setup was wrong, not the PRD.

**Per-edit pre-edit search log (edit 1 of 1):**
- (a) Subject: `strikes_this_season` semantics (stored counter vs. count derived from the inspection log).
- (b) Impl paths enumerated and read/grepped: `routes/subscriptions.py:83` (init 0 at creation); `routes/inspections.py:70-86` (unconditional `+= 1` on `TAGGED_REJECTED`; suspension only when `strikes >= max_strikes` and sub `ACTIVE`); `routes/subscriptions.py:206-231` (cure resets to 0); `services/core.py:224-228` (`recompute_strikes` deprecated to read-only, zero callers — verified by grep); `services/core.py:273-285` (`suspend_subscription`, doesn't touch strikes); `services/core.py:117-139` (season-end expiry clears `suspended_reason` but does NOT reset strikes); `routes/subscriptions.py:188-203` (cancel clears `suspended_reason` but does NOT reset strikes); `services/core.py:366` (serializer exposes the field); `routes/zones.py:33,100-101` (`max_strikes_per_season` default 3, editable in any status — affects threshold only).
- (c) Wording adjustments from the enumeration: said "only a successful cure payment returns it to zero" because cancel and expiry demonstrably do not reset the counter; left the increment unqualified by subscription status because `inspections.py:78` increments whenever a `SCHEDULED` ticket is `TAGGED_REJECTED`; added "starts at zero when the subscription is created" (subscriptions.py:83) since the removed derived-count phrasing had implicitly supplied the initial value; kept "PASSED and TAGGED_WARNING never increment" and the threshold sentence verbatim to stay consistent with the remaining quoted prose and the `strikes >= max_strikes and status == "ACTIVE"` check.

## Step 9: Complete PRD — 2026-08-11T15:05:00.000Z

Produced `/home/ubuntu/github/CodingPRD/tasks/task_1180_residential_yard_waste_composting_program/workspace/PRD_COMPLETED.md` (copy of PRD_FINALIZED.md + 32 inline changes; no new sections, no restructuring).

**Stats**
- Lines: 315 → 318 (+3); chars: 51,455 → 55,756 (**+4,301**)
- Ambiguity-pins: 28; Mismatch-revisions: 4

**Changes** (one bullet each; impl paths under `…/workspace/implementation/`):

- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` (1–100) or negative `offset` rejected with `ERR_INVALID_REQUEST` — response.py:60-84
- §2.3 — revise — ambiguity — `created_at` ordering ties broken by `id` ascending; same ordering for oldest-first credit consumption and cart-fee ordering — routes/*.py list handlers, routes/subscriptions.py:158, services/core.py:212
- §2.3 — revise — ambiguity — `has_more` pinned: true exactly when `offset` + items-in-page < `total_count` — response.py:29
- §2.3 — insert — ambiguity — enumerated per-endpoint exact-match list filters (zones by service_model/status; subscriptions by household_id/status/season_year; etc.) — routes/*.py list handlers
- §2.4 — insert — ambiguity — logical-clock stamps (`delivered_at`, `completed_at`) recorded in canonical whole-second `Z` form — db.py:57-60, routes/carts.py:108, routes/tickets.py:145
- §2.5 — revise — ambiguity — `version` starts at 1; `updated_at` equals `created_at` at creation — services/core.py:50-52
- §2.8 step 3 — revise — mismatch — resident-scoped reads extended to one's own **cart** (impl enforces ownership on GET /carts/{id}) — routes/carts.py:94-95
- §2.8 — insert — mismatch — pinned evaluation-order deviations: ownership evaluated after path resolution (step 4) and body parsing (step 5); ticket stop/tonnage capacity (step 9) runs after season-window (10) and route-published (11); delivery buffered-overlap (9) after facility-open/route-published (11); zone `OFF_SEASON` gate (7) before replacement-window shape (5) — routes/subscriptions.py:128-145, routes/tickets.py:60-83, routes/facilities.py:131-151, routes/zones.py:86-92
- §3.1 — insert — ambiguity — zone creation requires `season_end_date` on/after `season_start_date` — routes/zones.py:34-35
- §3.1 — insert — ambiguity — zone `name` and `service_model` immutable after creation — routes/zones.py:82-83
- §3.1 — insert — ambiguity — household `credit_balance_cents` and `compost_entitlement_gallons` start at zero — routes/households.py:30-31
- §3.2 — revise — ambiguity — "number of days in the season window" pinned as end−start date difference (not inclusive count) — services/core.py:197
- §3.2 — insert — ambiguity — optional `payment_cents` must equal the post-credit remainder exactly; under/over-payment → `ERR_INVALID_REQUEST` — routes/subscriptions.py:136-179
- §3.2 — revise — ambiguity — cancellation also clears `suspended_reason` to null — routes/subscriptions.py:200
- §3.2 — revise — ambiguity — cancel cascade skips tickets with `service_date` strictly after the current clock date — services/core.py:308-313
- §3.3 — insert — ambiguity — cart creation records `household_id`/`subscription_id` as given; no cross-check that the subscription belongs to the household — routes/carts.py:35-40
- §3.4 — revise — ambiguity — only `PUBLISHED` routes auto-archive; `DRAFT` routes never — services/core.py:142-148
- §3.4 — revise — ambiguity — ticket season window is the household's zone (via subscription); the route's zone is not cross-checked — routes/tickets.py:60-67
- §3.4 — revise — ambiguity — "future" skip condition pinned as `service_date` strictly after the current clock date — services/core.py:280-284
- §3.5 — insert — ambiguity — cure payment shortfall rejected with `ERR_INVALID_REQUEST` — routes/subscriptions.py:222-224
- §3.5 — revise — ambiguity — suspension skips tickets with `service_date` strictly after the current clock date — services/core.py:280-284
- §3.7 — insert — ambiguity — surge event creation requires `booking_window_end` strictly after `booking_window_start` and non-negative `capacity_slots` — routes/surge.py:38-49
- §3.8 — revise — ambiguity — facility `daily_receiving_capacity_lbs`/`safety_contamination_item_limit` adjustable in either status; `name` immutable — routes/facilities.py:82-92
- §3.8 — revise — ambiguity — buffered bay-overlap check ignores `REJECTED` deliveries — routes/facilities.py:144-145
- §3.8 — revise — ambiguity — receive `outcome` literals pinned as `ACCEPT`/`REJECT`; `gross_weight_lbs` and `contaminated_item_count` non-negative integers — routes/facilities.py:205-209
- §3.8 — insert — ambiguity — `per_household_cap_gallons` must be non-negative — routes/compost.py:38-39
- §3.8 — revise — mismatch — entitlement sums `COMPLETED` tickets across all of the household's subscriptions **regardless of season** (dropped "in the current zone season") — services/core.py:237-243
- §3.8 — revise — ambiguity — "remaining entitlement" defined as `compost_entitlement_gallons` minus gallons of `FULFILLED` claims across all giveback events — services/core.py:259-267
- §3.8 — revise — ambiguity — per-household cap counts only `FULFILLED` claims; `VOIDED` excluded — routes/compost.py:132-135
- §3.9 — revise — ambiguity — "budget fields" enumerated: `budget_cents`, `audience_size`, `cost_per_impression_cents`, `end_date` — routes/campaigns.py:102-127
- §4 — insert — ambiguity — undefined path or unsupported method rejected with `ERR_NOT_FOUND` (404) — app.py:25-31
- §5 — insert — mismatch — added missing catalogue row `ERR_PAYMENT_NOT_REQUIRED` | 409 (prose named it; impl returns 409) — errors.py:52, routes/subscriptions.py:148-149

Key findings: the four true mismatches were (1) the §5 catalogue omitting `ERR_PAYMENT_NOT_REQUIRED`, (2) the §2.8 pipeline's numbered order vs impl's actual ordering (ownership after resolution/parsing; capacity/overlap checks after temporal/referential gates on ticket creation and delivery scheduling), (3) resident-ownership scope omitting cart reads, and (4) the "current zone season" qualifier on entitlement recomputation, which impl does not enforce. Everything else — all 62 endpoint role assignments, state machines, fee/credit/entitlement formulas, OCC, cascades, and error IDs — matched the finalized PRD verbatim.
