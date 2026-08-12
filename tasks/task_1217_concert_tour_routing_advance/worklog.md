# Worklog — task_1217_concert_tour_routing_advance

Scenario: Concert Tour Routing & Advance (touring artist management): routing optimization by market, travel day & venue availability, hold/confirm workflow with promoters, budget per show & tour P&L projection, advance packet exchange (tech rider/hospitality/immigration), crew/bus/truck logistics & day sheet, radius clause & competitive date conflicts, ticket on-sale timing & marketing spend, settlement roll-up across tour.
Difficulty: generate task hard than expert level!

## Step 1: Create Task Directory — 2026-08-12T00:01:10.000Z

Pre-assigned output folder `tasks/task_1217_concert_tour_routing_advance` with `workspace/` subdirectory already existed; verified present. Skipped auto-index scan per instructions.

## Step 2: Generate Scaffold — 2026-08-12T00:28:35.000Z

All three files are written, parseable, and pass the lint with a clean verdict.

## Summary

**Task directory:** `/home/ubuntu/github/CodingPRD/tasks/task_1217_concert_tour_routing_advance/`

**Verdict (verbatim from `scaffold_lint.py`):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Counts:**
- Entities: **11** (Tour, Market, Venue, RoutingLeg, Show, PromoterHold, AdvancePacket, BudgetLine, MarketingSpend, Settlement, ComplianceHold)
- State machines: **8** (Tour status, Tour posture, RoutingLeg, Show status, Show posture, PromoterHold, AdvancePacket sections, Settlement)
- Calculations: **8** (projected_show_pnl [dual-variant], settlement_artist_share [max-of-two-arms], marketing_cpa [per-line vs blended], settlement_variance_flag, routing_leg_drive_time, radius_clause_check, on_sale_lead_check, hold_expiry_check)
- Endpoints: **77** (nested CRUD + flat FK-reverse search + computed reads + `/_clock/set_current_utc`)
- Errors: **32**
- Validations: **18** ordered priorities across auth/existence/state/business_temporal/business_safety/business_constraint/business_fiscal/business_referential
- Roles: **5** (TourManager, Promoter, VenueRep, SettlementAccountant, Any) — segregation-of-duties on settlement submit vs verify
- Concurrency rules (OCC): **3** (`show-confirm-stale-tour`, `hold-counter-stale-show`, `advance-packet-approve-stale`)
- §1.8 difficulty instances: **18** (2 per rule × 9 rules)
- §1.9 corner instances: **30** (across 9 sections of the claim-extraction guide)

**Notable design decisions (harder-than-expert calibration):**
- **Posture-driven gating as primary archetype**, with both Tour-level posture (derived from ComplianceHold severity mix) AND Show-level posture (AND of tour posture and advance packet state) gating the same confirm/advance/settle transitions
- **Dual-variant calculation** on Show P&L that flips between `PRE_ON_SALE` (capacity-based) and `POST_ON_SALE` (actual + decay) variants based on the logical clock — tested by driving the clock across the boundary
- **Cyclic PromoterHold** state machine (PENDING↔COUNTERED up to MAX_COUNTER_ROUNDS) plus **parallel state dimensions** on Show (status × posture)
- **Two different temporal-overlap semantics** on different resources: Venue.booked_dates uses point-membership (exact date equality), Market radius-clause uses half-open interval arithmetic on day windows
- **Two compensating invariants** on different conserved quantities: venue.booked_dates set membership (confirm+cancel = identity) and Tour.projected_gross_cents monetary aggregate (confirm+cancel = 0 drift)
- **Validation priority pairs** exercise state-vs-business_fiscal (settlement verify) and business_temporal-vs-business_safety (show confirm)
- **OCC concurrency** on three parents (Tour, Show, AdvancePacket) with dedicated 412 error codes, exercised via stale-version chains in test recipes
- **Segregation of duties** on Settlement (Promoter submits, SettlementAccountant verifies/pays, with `ERR_SEGREGATION_OF_DUTIES` on X-User-ID collision)
- **Default clock time 2026-05-01T00:00:00Z** declared on `/_clock/set_current_utc` so deadline/TTL rules are deterministic
- **Flat FK reverse-reachability endpoints** (`/tours/markets`, `/tours/venues`, `/tours/shows`, etc.) added alongside nested paths so every FK in §1.1 has a sub-resource or filtered-list GET — passes lint rule (f)

(Note: first scaffold subagent turn ended mid-design with zero files written; resumed via SendMessage with its design context intact, and it completed all three files, self-correcting a YAML flow-sequence syntax error in SCAFFOLD_CORNER_DESIGN.yaml during its lint pass.)

## Step 3: Copy Shared Files — 2026-08-12T00:28:35.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1217_concert_tour_routing_advance/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-12T00:37:08.000Z

All checks pass. The PRD is complete on disk.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1217_concert_tour_routing_advance/workspace/PRD.md` — 318 lines (47.6 KB), non-empty, ends at §5 with no audit footer.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications (10 subsections): 2.1 RBAC with per-role identity prose (all five roles `opaque`, individually named); 2.2 response envelope emitted **verbatim** from `section-2.2-response-structure.md`; 2.3 pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending); 2.4 common properties (`id`/`created_at`/`updated_at`/`version`, plus `packet_revision` OCC nuance); 2.5 logical clock (startup default `2026-05-01T00:00:00Z`, no wall-clock fallback, three sweeps); 2.6 posture derivation/gating; 2.7 integer-cents + round-half-up; 2.8 OCC (3 rules with exact `expected_*` fields, error IDs, HTTP 412); 2.9 left-to-right 404 + flat-fetch routes (all path/query params named); 2.10 fixed validation priority order (auth → role → 404 → FK 422 → OCC 412 → state → posture → domain rules).
- §3 Business Logic (8 subsections, lifecycle-grouped): tour staging, routing legs/rest, hold negotiation, confirm/radius/OCC, advance packet/day sheet, on-sale/tickets/marketing, settlement/SoD, tour financials/close.
- §4 Endpoint table — all 78 scaffold endpoints, 4 columns only.
- §5 Error catalogue — all 30 errors, 2 columns only.

**Coverage audit (hard contracts):**
- Contract 1 Field-Name Coverage: 88 required (entity fields + endpoint inputs + query params + path params), 88 present, 0 missing — **PASS**
- Contract 2 Rule Coverage: validation priority order expressed (§2.10); 3/3 OCC rules with endpoint + occ field + error_id + 412; all 31 state-machine transitions expressed with preconditions/error IDs/side effects; all 7 calculations in precise reconstructible prose (0.65/0.35/350-cent constants, 55 mph/480-min strict boundary, 14-day lead with equality allowed, 72h/24h/3-round hold rules, 50,000/500,000-cent variance inclusive boundaries, min-of-both radius sweep with half-open date boundary and STANDARD-at-edge/CRITICAL-inside grading); all `applies_to` scopes and endpoint side effects covered — **PASS**
- Contract 3 §3 Path Purity: 353 backtick tokens scanned, 0 paths, 0 bare methods, 0 method+path combos — **PASS**
- Aux checks: 30/30 error IDs in prose, all state enum values present, 78/78 endpoint paths in §4, no pseudocode operator leaks (`==`, `>=`, `+=`, `AND`/`OR`), no fuzzy words (single "around" hit is geometric: "radius around the market centroid").

**Adjudications made:**
1. Scaffold validation 9 lists `PATCH show/on-sale` as an applies_to target, but no such endpoint exists in the endpoint table — I did not invent it; the lead-time rule is expressed at show creation (where `on_sale_at` is input) and re-verified at confirm, matching both the calculation and the confirm precondition.
2. `Show.capacity` field description says "venue.capacity at confirm time" while the accept transition says the snapshot happens at first acceptance (HOLD_PLACED) — I followed the state machine (snapshot at acceptance, frozen thereafter), which is the behavior-bearing entry.
3. Venue `booked_dates` entity definition says confirmed-or-later shows, while hold-accept side effect says the calendar updates at acceptance — both transcribed faithfully (accept updates the calendar; confirm adds `show_date`; withdraw/expire/cancel release it).
4. `ERR_BUDGET_OVERRUN`'s "per-show budget cap" has no scaffold constant — described as the tour's per-show budget cap without inventing a number.
5. §4 table role column uses the scaffold's explicit four-role lists for GETs (the `Any` role is described in §2.1 prose rather than the table, matching the scaffold's endpoint rows).

## Step 5: Generate Unit Tests — 2026-08-12T01:09:00.000Z

Generation complete. Summary:

**Helper files written** (`/home/ubuntu/github/CodingPRD/tasks/task_1217_concert_tour_routing_advance/test_helpers/`): `types.py` (11 entities, 13 enums — all entities carry full common fields), `api_client.py` (one method per PRD §4 endpoint, incl. flat fetch/search routes and `/_clock/set_current_utc`), `api_errors.py` (all 32 error IDs with HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity structural assertions), `factories.py`, `constants.py` (0.65/0.35 factors, 350¢ variable cost, 55 mph / 480 min, 14-day lead, 72h TTL / 24h extension / 3 rounds, 50k/500k variance), `test_users.py` (5 opaque roles + per-user builders for the segregation-of-duties test), `fixtures.py` (5-tier composites: staged tour → held show → confirmed → advanced → performed → paid, packet OCC approval chain, counter helper, clock control), `__init__.py` barrel.

**Test files** (`test_suite/`): `conftest.py` + 11 test modules, **75 collected tests (72 test functions)**.

**Coverage audit (self-check)**
- Queue A: all **18/18** difficulty instances translated, each with **≥2 tests** (38 tests).
- Queue B: all **30/30** non-stub corner instances translated (no `excluded_because` stubs exist in this task), each with **≥1 test** (34 tests).
- Every test docstring ends with exactly one verbatim `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line; audit confirms no untagged, dual-tagged, or dangling tags.
- **88 long (≥8-word) PRD citations all survive verbatim grep** of `workspace/PRD.md` (whitespace-normalized). No `skip`/`skipif`/`xfail` anywhere.
- `python3 -m py_compile` passes on all files; all 13 modules import cleanly; `pytest --collect-only` succeeds (75 tests).

**Skipped instances: 0.** Two instances needed PRD-first corrections to the recipe (noted as PRD/design-index bugs, assertions follow the PRD):
- `Difficulty/resource_temporal_overlap/radius_clause_half_open_window` — the recipe asserts `ERR_RADIUS_CONFLICT` at diff == window, but PRD §3.4 grades an exactly-at-edge conflict as `STANDARD` (non-blocking, opens a hold, tour → RESTRICTED); only strictly-inside is `CRITICAL`. Tests assert the PRD behavior (edge → success + STANDARD hold + RESTRICTED; +1 day → clean; strictly inside → `ERR_RADIUS_CONFLICT`).
- `Difficulty/priority_pair_validation_conflict/business_safety_vs_business_temporal_on_confirm` — the recipe's venue-unavailable setup is unreachable (creating a show with a date outside `available_dates` is itself rejected per PRD §3.3, and a booked-date blocker show in another market within the window is itself radius-blocked from confirming). Translated using the same category pair via the confirm-time on-sale-lead gate (priority 9, business_temporal) vs the radius sweep (priority 10, business_safety), ordered by PRD §2.10's verbatim domain-rule sequence, plus an isolated `ERR_RADIUS_CONFLICT` test.

Other deliberate PRD-first adjustments: budget lines in projection tests are created after confirm (so `is_committed` is true under any reading of PRD §3.7); segregation-of-duties and lockdown setups patch `tickets_sold` so variance stays below MATERIAL (PRD §2.10 evaluates variance before segregation); 4a's pre-cancel gross uses the PRD-correct 58,500,000 (the design YAML's 5,850,000 is an arithmetic typo for 9000×10000×0.65).

## Step 6: Generate Implementation — 2026-08-12T01:09:00.000Z

Implementation complete and verified. Summary:

## File list — `tasks/task_1217_concert_tour_routing_advance/workspace/implementation/`

- `start.sh` — guarded install (no-op once Flask importable), `exec python3 app.py`, foreground, `$PORT` (default 10000), binds `0.0.0.0`
- `requirements.txt` — `flask>=3.0,<4`
- `app.py` — app assembly, ApiError/HTTP error handlers (enveloped), static folder disabled for exact route parity
- `db.py` — in-memory dict store (11 collections), logical clock starting exactly `2026-05-01T00:00:00Z`, entity factory (`version` starts at 1), **no seeding of any kind**
- `errors.py`, `response.py` — scaffold envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; error `data.error_id`/`message`; pagination `limit`/`offset`/`total_count`/`has_more` in meta, defaults 10/0, clamp 1..100)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (5 exact role spellings), body/field validators → `ERR_INVALID_REQUEST`, strict ISO date/datetime parsing
- `services.py` — posture derivation, dual-variant `projected_show_pnl` (Decimal, ROUND_HALF_UP per show before summing), radius sweep, artist share, variance flags, drive time, CPA, clock/hold sweeps, left-to-right nested resolvers, serializers (internal `_`-keys never exposed)
- `routes/` — 12 modules: tours, markets, venues, legs, shows, holds, packets, budget, marketing, settlements, compliance, clock

## Verification results

1. `bash -n start.sh` — clean
2. `python3 -m py_compile` on all 18 `.py` files — clean
3. Smoke boot via `PORT=18231 bash start.sh`: `GET /tours` → HTTP 200 array envelope with pagination meta; `GET /tours/markets` (flat, role `Any`) → 200; missing headers → 400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; server killed cleanly
4. Route parity: **77 declared vs 77 registered, 0 missing, 0 extra**
5. Beyond the smoke: two live assertion suites (~90 assertions) passed — full lifecycle (tour→market→venue→show→hold→confirm→on-sale→clock crossing→advance→tickets→budget→marketing→perform→settle→verify→pay→close) with exact cent-level projection checks (6,500,000/350,000 pre-on-sale; 3,500,000/0 post; 8,700,000/280,000 after 800 tickets), plus edge cases (expiry at exact boundary, 3-counter limit + 24h extensions, STANDARD vs CRITICAL radius conflicts at window edge ±1 day, RESTRICTED/FROZEN gating, cancel/withdraw cascades, leg anchoring/rest/480-minute boundary, OCC 412s, SoD 403, RBAC and validation ordering)

## Notable interpretation decisions (PRD-admitted latitude)

- **Radius distance**: markets carry no coordinates, so `distance(m1,m2) <= min(radius)` is unverifiable from stored data; same-tour cross-market pairs are treated as in-range, leaving the exclusivity-window test operative (half-open: gap == min window conflicts as STANDARD, strictly inside CRITICAL).
- **booked_dates**: per the Venue entity description, it reflects CONFIRMED+ shows only; hold acceptance's "calendar update" is a soft block not serialized, otherwise confirm's "not in booked_dates" precondition would be unsatisfiable.
- **ON_SALE→IN_PROGRESS crossing**: literal PRD/scaffold rule — only CONFIRMED shows trigger it; a show advanced before its on-sale moment does not.
- **Projection set**: kept as {CONFIRMED, ADVANCED, PERFORMED, SETTLED} per PRD §3.8 + entity field text, over the conflicting §3.7 "drops from the projection set" remark.
- **ERR_BUDGET_OVERRUN**: no budget-cap field exists anywhere in the entity model, so the cap check never fires.
- **Expired-hold transitions**: accept/counter/respond on an expired hold → `ERR_HOLD_EXPIRED` (its catalog condition); reject/withdraw on a terminal hold → `ERR_INVALID_STATE`.
- **Ferry-leg waiver**: no ferry-leg flag exists in the model, so leg-lock anchoring always applies. Rest-day rule: a `crew_rest_required` leg locking adjacent (leg_index ±1) to a LOCKED leg with <2 calendar days between travel dates → `ERR_REST_VIOLATION`; clock-advance rest rechecks are vacuous.
- **Settled rollups**: `settled_gross_cents` = PAID settlements' box-office gross; `settled_cost_cents` = sum of budget-line `actual_cents` (null→0) for those shows.
- Cancel resets only non-PENDING packet sections, bumping `packet_revision` once per changed section; `created_at`/`updated_at` use wall clock while all behavioral timing (expiry, on-sale, performed gating) uses the logical clock.

(Orchestrator note: independent route-parity re-check after the subagent exited confirmed 77 declared = 77 registered (method, path) pairs, 0 missing, 0 extra.)

## Step 7: Run Tests and Iterate — 2026-08-12T01:17:06.000Z

Summary:

- **Iterations run**: 2 sweeps (round 1: 4 consistent failures × 8 rounds; round 2 after fixes: 75/75 × 8 rounds, clean).
- **Tests deleted**: none — all 4 failures traced to PRD-covered, uniquely-determined rules with faithful tests.
- **Fixes applied to `test_helpers/`**: none.
- **Fixes applied to `test_suite/`**: none.
- **Fixes applied to `implementation/`** (3 files, all STEP 3 implementation bugs):
  1. `routes/holds.py` — `_require_unexpired`: previously raised `ERR_HOLD_EXPIRED` whenever hold status was already `EXPIRED`. Since the expiry sweep (PRD §3.3) moves the hold to `EXPIRED` before any transition handler runs, the permissible-state check (PRD §2.10 priority 6, `ERR_INVALID_STATE`) fires first; `ERR_HOLD_EXPIRED` is now reserved for a hold whose expiry instant arrived but status is still `PENDING`/`COUNTERED`.
  2. `routes/shows.py` — show creation: removed the `booked_dates` membership check from the create-time `ERR_VENUE_UNAVAILABLE` gate. PRD §3.3 requires only window + `available_dates` at create; the `booked_dates` exclusion is verbatim a confirm-time gate in PRD §3.4. The over-check was rejecting legitimate second-show setup for the point-collision confirm test.
  3. `routes/settlements.py` — `submit_settlement`: reordered to check `Show.status == PERFORMED` before resolving the Settlement. PRD §3.7 verbatim: "Submission requires the settlement to be in `DRAFT` and the show to be `PERFORMED` (otherwise `ERR_SHOW_NOT_PERFORMED`)" — for a non-performed show the settlement doesn't exist yet (spawned at mark-performed), so the show-state gate must fire instead of 404.

Final state: 8/8 parallel rounds, 75/75 tests passing each.

(Orchestrator verification: all 8 `results.{1..8}.json` files confirmed on disk, each `passed: 75 / 75, failed: 0`.)

## Step 8: Finalize PRD — 2026-08-12T01:24:21.000Z

PRD_FINALIZED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1217_concert_tour_routing_advance/workspace/PRD_FINALIZED.md`.

## Summary

**Line counts / delta**: PRD.md 317 lines → PRD_FINALIZED.md 317 lines (0% line delta; all three edits are inline sentence insertions into existing paragraphs, no new sections, no deletions).

### Changes (one bullet per edit)

- **§3.3 (show-creation paragraph)** — insert — added "The venue's `booked_dates` calendar is not consulted at creation: excluding an already-booked date is a confirm-time gate (§3.4), not a create-time one." — `implementation/routes/shows.py:52-66` (create gate checks window + `available_dates` only; the `booked_dates` exclusion lives at confirm, `shows.py:152-161`).
- **§3.3 (Expiry bullet)** — insert — added "Because the sweep runs ahead of any transition handler's own checks, a hold that has already been moved to `EXPIRED` is rejected by the permissible-state check of §2.10 with `ERR_INVALID_STATE`; `ERR_HOLD_EXPIRED` is surfaced only for a hold still in `PENDING` or `COUNTERED` whose expiry instant has been reached." — `implementation/routes/holds.py:39-47` (`_require_unexpired`), `:31-36` (`_guarded_hold` sweeps first).
- **§3.7 (settlement submission paragraph)** — insert — added "Because the settlement is spawned only when the show is marked performed, the show-state gate fires before the settlement is resolved: submitting against a show that is not `PERFORMED` is rejected with `ERR_SHOW_NOT_PERFORMED`, not a not-found error." — `implementation/routes/settlements.py:46-54` (PERFORMED check precedes settlement resolution).

### Per-edit pre-edit search log

**Edit 1 — §3.3 create gate**
- (a) Subject: create-time `ERR_VENUE_UNAVAILABLE` gate vs. `booked_dates` membership.
- (b) Paths enumerated (grep `booked_dates|ERR_VENUE_UNAVAILABLE` across impl): `routes/shows.py:52-66` (create gate: window + `available_dates` only), `shows.py:152-161` (confirm gate: `available_dates` + `booked_dates`), `shows.py:178` (confirm appends date), `shows.py:287-291` (cancel releases), `routes/holds.py:226-227` (withdraw releases if present; `accept_hold` does not touch `booked_dates`), `routes/venues.py:64` (initialized `[]`), `services.py` (no references). All booked-date exclusion behavior occurs only at confirm — wording consistent everywhere.
- (c) Wording framed as a pure negative scoping ("not consulted at creation … confirm-time gate (§3.4)") so it makes no claim about what acceptance/withdraw do to `booked_dates`, avoiding conflict with §3.3's acceptance bullet (out of scope per HARD SCOPE).

**Edit 2 — §3.3 Expiry bullet**
- (a) Subject: error precedence for transitions on expired holds (`ERR_HOLD_EXPIRED` vs `ERR_INVALID_STATE`).
- (b) Paths enumerated (grep `ERR_HOLD_EXPIRED|sweep_hold|sweep_all_holds|sweep_clock`): `routes/holds.py:31-36` (`_guarded_hold` sweeps before every transition handler), `holds.py:39-47` (`_require_unexpired` — fires only when status ≠ EXPIRED and clock ≥ expiry), `holds.py:98-230` (counter/respond-counter/accept call `_require_unexpired`; reject/withdraw rely on status whitelists only), `services.py:355-369` (`sweep_hold`, `sweep_all_holds`), `services.py:372-400` and `routes/clock.py:20` (`sweep_clock` on clock advance). Confirmed the sweep precedes all five transition handlers' state checks, so an `EXPIRED` hold always yields `ERR_INVALID_STATE`; the added sentence mirrors the impl's own comment almost verbatim.
- (c) Wording says `ERR_HOLD_EXPIRED` "is surfaced only for a hold still in `PENDING` or `COUNTERED` whose expiry instant has been reached" — deliberately under-determined (does not claim the branch is reachable), so it stays true even though the sweep makes it unreachable in practice, and it reinterprets rather than contradicts the counter bullet's existing "else `ERR_HOLD_EXPIRED`".

**Edit 3 — §3.7 settlement submission**
- (a) Subject: gate ordering at submit — show-PERFORMED check vs. settlement-resolution 404.
- (b) Paths enumerated (grep `ERR_SHOW_NOT_PERFORMED|settlement_for_show|store["settlements"]`): `routes/settlements.py:37-58` (submit: PERFORMED → settlement 404 → DRAFT `ERR_INVALID_STATE`), `settlements.py:21-27` (`_resolve_settlement` still 404s for get/verify/pay — unchanged and untouched by the wording), `routes/shows.py:252-268` (mark-performed is the only settlement creation site), `services.py:117-121` (`settlement_for_show`), `routes/tours.py:143` (close; read-only).
- (c) Wording scoped explicitly to submission ("submitting against a show that is not `PERFORMED`") so it says nothing about get/verify/pay 404 behavior; original sentence kept verbatim, clarification appended as a new sentence.

No other edits: all three Step 7 items were implementation bugs where the PRD's composed meaning already favored the fixed behavior; the inserts pin the exact points where the PRD's local prose had misdirected the Step 3 implementer, without narrowing any other behavior.

## Step 9: Complete PRD — 2026-08-12T01:41:17.000Z

All edits verified. PRD_COMPLETED.md is fully written. Here is the summary.

## Summary

**Files:** `/home/ubuntu/github/CodingPRD/tasks/task_1217_concert_tour_routing_advance/workspace/PRD_FINALIZED.md` (317 lines / 48,375 chars) → `/home/ubuntu/github/CodingPRD/tasks/task_1217_concert_tour_routing_advance/workspace/PRD_COMPLETED.md` (318 lines / 53,256 chars; **+1 line, +4,881 chars**). All changes are inline inserts/revisions; no sections added.

**Counts:** 27 ambiguity-pins, 15 mismatch-revisions (33 change bullets below; some bullets bundle one pin + one revision in the same sentence).

### Ambiguity-pins
- §2.2 — insert — ambiguity — 5xx failures use the error envelope with `ERR_INTERNAL` — implementation/app.py:40-42
- §2.3 — insert — ambiguity — invalid `limit`/`offset` → `ERR_INVALID_REQUEST`; `created_at` ties broken by insertion order; `has_more` = offset+returned < total — implementation/response.py:41,55-88
- §2.4 — revise — ambiguity — `version` starts at **1** at creation — implementation/db.py:50
- §2.4 — revise — ambiguity — `packet_revision` starts at **0** — implementation/routes/shows.py:101
- §2.5 — insert — ambiguity — clock accepts any timestamp (no monotonicity check), responds `{"current_utc": ...}` — implementation/routes/clock.py:14-21
- §2.7 — insert — ambiguity — all money/distance/day-count/quantity write fields non-negative (`ERR_INVALID_REQUEST`), except `capacity` strictly positive and `territory_rank`/`leg_index` unbounded — implementation/middleware.py:86-98 + all `v_int` call sites
- §2.9 — insert — ambiguity — multiple filters combine conjunctively — implementation/routes/venues.py:105-110
- §2.10 — insert — ambiguity — strict field formats (non-empty strings, strict `YYYY-MM-DD`, offsetless timestamps read as UTC); unrecognized paths → `ERR_NOT_FOUND` 404 — implementation/middleware.py:75-199; app.py:34-38
- §3.1 — insert — ambiguity — `curfew_local_time` validated as 24-hour `HH:MM` — implementation/routes/venues.py:37-40
- §3.2 — revise — ambiguity — exact rest rule: only when the locking leg's own `crew_rest_required` is true, only already-`LOCKED` legs with `leg_index` differing by one are examined, travel dates must be ≥2 calendar days apart — implementation/routes/legs.py:109-124
- §3.3 — insert — ambiguity — show's market/venue need same-tour resolution only; venue's own market need not match — implementation/routes/shows.py:38-51
- §3.3 — insert — ambiguity — new show zeroes `capacity`/`tickets_sold`/`gross_potential_cents`/projections — implementation/routes/shows.py:83-88
- §3.3 — insert — ambiguity — placing a hold has no show-state precondition, no concurrency limit; `versus_pct` 0–100 **inclusive** — implementation/routes/holds.py:50-75
- §3.3 — insert — ambiguity — countered terms held aside and never exposed on the hold until accepted via respond-counter — implementation/routes/holds.py:123-126; services.py:408-409
- §3.3 — revise — ambiguity — withdrawal block reads the show's *current* status (SETTLED/CANCELLED allow it); withdrawing an accepted hold from a CONFIRMED show leaves it CONFIRMED — implementation/routes/holds.py:202-230
- §3.4 — insert — ambiguity — one `RADIUS_CONFLICT` compliance hold opened per conflicting show — implementation/routes/shows.py:180-192
- §3.4 — revise — ambiguity — cancel cascade also bumps `packet_revision` once per reset section, zeroes the show's projections, recomputes tour totals — implementation/routes/shows.py:298-316
- §3.5 — insert — ambiguity — unrecognized `section` path value → `ERR_NOT_FOUND` — implementation/routes/packets.py:33-39
- §3.5 — insert — ambiguity — no API transition into `NOT_REQUIRED`; honored but unreachable — implementation/routes/packets.py (absence); services.py:135-142
- §3.6 — revise — ambiguity — open-on-sale from non-ROUTING → `ERR_INVALID_STATE` — implementation/routes/tours.py:88-89
- §3.6 — insert — ambiguity — ticket update: non-negative, uncapped vs capacity, no show-state gate — implementation/routes/shows.py:319-333
- §3.6 — revise — ambiguity — flight-date ordering not validated — implementation/routes/marketing.py:29-30
- §3.7 — revise — ambiguity — settlement spawns zeroed with `variance_flag` `NONE` — implementation/routes/shows.py:253-267
- §3.8 — revise — ambiguity — projection recompute trigger list (confirmation, advance, performance, cancellation, budget create/update, ticket update, clock crossing, payment) — implementation/routes/budget.py:46-49,89-92; shows.py:194-196,221-226,308-315,329-332; settlements.py:126-127
- §3.8 — insert — ambiguity — settled gross = settlement's `box_office_gross_cents`; settled cost = sum of `actual_cents` over all lines (committed or not), null → 0 — implementation/services.py:239-249
- §3.8 — revise — ambiguity — resolve requires `ACTIVE`, else `ERR_INVALID_STATE` — implementation/routes/compliance.py:83-86
- §3.8 — insert — ambiguity — enter-settlement-review/close from wrong tour status → `ERR_INVALID_STATE` — implementation/routes/tours.py:111-116,136-139

### Mismatch-revisions
- §2.6 — revise — mismatch — `FROZEN` no longer blocks settlement (no posture check exists in settlement submit/verify/pay) — implementation/routes/settlements.py (absence)
- §2.6 — revise — mismatch — show `posture` is a read-only derived field, never consulted as a gate; `NOT_REQUIRED` counts complete — implementation/services.py:150-158,428-431
- §3.1 — revise — mismatch — `country_code` carried as plain string; no two-letter ISO validation — implementation/routes/markets.py:23
- §3.2 — revise — mismatch — derived leg fields computed only at creation; no distance-update operation exists — implementation/routes/legs.py:49-59
- §3.2 — revise — mismatch — ferry-leg anchoring waiver unreachable (no ferry flag), so anchoring applies to every leg — implementation/routes/legs.py:90-105
- §3.2 — revise — mismatch — no manual rest-override; locking never opens a `REST_VIOLATION` hold — implementation/routes/legs.py:125-130
- §3.3 — revise — mismatch — hold acceptance does **not** update `booked_dates` (only confirmation does) — implementation/routes/holds.py:157-184
- §3.3 — revise — mismatch — expiry releases nothing (no soft-block exists); transition-endpoint sweep covers only the target hold; `ERR_HOLD_EXPIRED` surfaces only for non-swept statuses (in practice `ACCEPTED`) on counter/respond/accept; reject/withdraw have no expiry guard — implementation/routes/holds.py:31-47,202-230; services.py:355-369
- §3.4 — revise — mismatch — markets carry no coordinates, so the radius/distance predicate is not evaluated; any two distinct markets count as in-range, leaving the exclusivity-window test operative — implementation/services.py:277-305
- §3.5 — revise — mismatch — reject retains no rejection record; section returns straight to `PENDING` (visible only via `packet_revision`) — implementation/routes/packets.py:88-102
- §3.6 — revise — mismatch — show-level blended CPA is not exposed anywhere (removed computation prose) — implementation/services.py:344-348 (per-line only)
- §3.7 — revise — mismatch — mark-performed keeps the show **in** the forward projection set (`PERFORMED` ∈ set) — implementation/services.py:29; routes/shows.py:249-251
- §3.7 — revise — mismatch — no budget-cap field exists, so the fiscal guard never fires and `ERR_BUDGET_OVERRUN` is never raised — implementation/routes/settlements.py:95-97
- §3.7 — revise — mismatch — payment recomputes projections with the show still in the set as `SETTLED`; `is_committed` fixed at creation and never changes; budget lines always editable, `actual_cents` nullable — implementation/routes/settlements.py:111-128; routes/budget.py:42,73-93
- §4 — revise — mismatch — clock endpoint lives outside `/tours`; day-sheet response contains no legs — implementation/routes/clock.py:14; routes/shows.py:336-354
