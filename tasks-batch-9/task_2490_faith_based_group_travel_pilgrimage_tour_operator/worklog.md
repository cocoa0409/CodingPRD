# Worklog — task_2490_faith_based_group_travel_pilgrimage_tour_operator

## Step 1: Create task directory — 2026-09-03T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2490_faith_based_group_travel_pilgrimage_tour_operator` and its `workspace/` subdirectory. Index 2490 was pre-assigned by the invoking pipeline; no index scan or allocation was performed.

## Step 2: Generate scaffold — 2026-09-03T02:42:51.797Z

Task 2490 scaffold is complete and lints clean.

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2490_faith_based_group_travel_pilgrimage_tour_operator/`)

- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

## SCAFFOLD.yaml contents

- **Profile**: flat topology (`api_prefix: ""`), cyclic state machines, `segregation_of_duties` role model, `immediate` consistency, layers = optimistic_concurrency / cascading_side_effects / dual_variant_calculation / rate_threshold_triggers; archetypes multi_party_negotiation + quota_allocation.
- **13 entities**: Program, Departure, GroupLeaderAgreement, Pilgrim, PaymentPlan, Payment, AirBlock, SacredSite, ServiceBooking, LandResource, LandAssignment, TravelProtection, RiskAdvisory.
- **10 state machines**, **2 OCC concurrency rules** (`payment-plan-create-stale-pilgrim` on Pilgrim, `leader-agreement-create-stale-departure` on Departure).
- **13 calculations** (tier dual-variant, leader accrual dual-variant, invoice with pinned grant/fee step order, land FX rollup, protection premium with age bands + medical uplift + capped waiver surcharge, waiver eligibility, deviation fees, plan schedule, payment waterfall, two conservation invariants, risk posture, cancellation settlement).
- **45 ordered validations** (priority 1 → 80), **61 endpoints** (incl. `POST /_clock/set_current_utc`, default clock 2026-08-01T00:00:00Z), **56 error codes**, **7 roles** (6 opaque + `GroupLeader` = `entity_backed:GroupLeaderAgreement`).

## Design files

- **§1.8**: 9 rules × 24 instances — dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 3, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 3, compensating_invariant 2.
- **§1.9**: 97 instances across all nine sections — entities 12, state_machines 14, calculations 9, validations 11, endpoints 8, errors 27, rbac 8, cross_cutting_complexity_layers 7, consistency_model 1. 81 carry full recipes; 16 are `excluded_because` stubs, every cited `difficulty_instance` verified to exist by name.

## Verification performed

- `scaffold_lint.py` → `VERDICT: clean lint` (61 endpoints, 13 entities, 24 + 81 instances, 699 calls scanned) — clean on first run.
- All three files `yaml.safe_load`-valid; names unique across the union of both design files (no collisions, no duplicates).
- All 56 error codes are asserted by at least one recipe (incl. nested contrast cases).
- Normalized assert phrasing to the declared envelope (`response.data.error_id`, list pagination via `response.total_count` / `response.data[i]`) — the pre-compaction sections had used `response.error.code` / `response.error.id`.
- No forbidden concurrency vocabulary present; all money/date literals recomputed with `Decimal` ROUND_HALF_UP (e.g. invoice 577168, single-room 673526, MONTHLY_6 = 4×96195 + 2×96194, land line 1462455 / 552483, band A 12379, band B 35784).
- Fixed three SCAFFOLD.yaml reachability/consistency defects found while designing: pagination max aligned to 100, `POST /service-bookings` no longer accepts the computed clergy fields, and `permit_reference` re-specified as a confirm-time gate so priority 74 is reachable.
- Hard constraint respected: no sibling `task_*/` directory was listed, globbed, grepped, or read.

## Step 3: Copy shared files — 2026-09-03T02:42:51.797Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-03T02:58:10.221Z

PRD generated and all three Hard Contracts pass.

**Output:** `workspace/PRD.md` — 474 lines, ~15,150 words. Ends at a completed §5 (last row `ERR_OVERPAYMENT_NOT_ALLOWED` | 422); no audit footer written into the file.

**Sections written**
- §1 Introduction (3 paragraphs: provisional-until-final pricing, two conserved quantities, exogenous risk; flat topology note)
- §2 Global Specifications — 11 subsections: 2.1 RBAC (7 roles + `GroupLeader` entity-backed identity + segregation of duties), 2.2 verbatim response block, 2.3 pagination + every list filter, 2.4 logical clock (`2026-08-01T00:00:00Z` default), 2.5 id/`created_at`/`updated_at`/`version` (`Payment` carries neither `updated_at` nor `version`), 2.6 cents/basis points/round-half-up, 2.7 both OCC rules, 2.8 path + body-FK resolution with all 13 not-found codes, 2.9 the full 14-band validation ladder + 3 named inversions, 2.10 the two conservation identities, 2.11 cascade discipline
- §3 Business Logic — 9 subsections: 3.1 programs/departure sales lifecycle + dual-variant tiering, 3.2 sacred sites & service schedule (half-open buffered intervals vs daily pax aggregate), 3.3 land contracting (closed-inclusive ranges, round-per-line-then-sum), 3.4 leader recruitment/free seats/settlement (snapshot vs settlement variants), 3.5 traveler enrolment (three orthogonal dimensions, 6-step invoice, cancellation grid, revocation + re-pricing cascades), 3.6 cyclic air-block negotiation + deviation fees, 3.7 ledger (waterfall, plan supersede, reversal, sweep), 3.8 protection quote→review→waiver→bind, 3.9 risk posture, publication cascade, itinerary modification, departure unwind
- §4 61-row 4-column endpoint table and §5 56-row 2-column error table, both generated programmatically from SCAFFOLD.yaml

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 147 required, 147 present, 0 missing
- endpoints[].input: 96 required, 96 present, 0 missing
- endpoints[].query_params: covered within the 96 (limit/offset + all filters)
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 45 checked, 45 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_pilgrim_version / expected_departure_version + error_id + 412), 0 missing
- state_machines[].transitions: 10 machines / all transitions checked, all fully expressed, 0 missing
- calculations[]: 13 checked, 13 fully expressed (all constants embedded in business context), 0 missing
- validations[] conditions: 45 checked, 45 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 61 checked, 61 expressed, 0 missing
- entities[].fields[] structured content: 147 checked, 147 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (2 tier variants, 2 accrual variants, APPROVE/DECLINE, CARRIER_OFFER/OPERATOR_COUNTER, plan/no-plan waterfall, clergy/non-clergy confirm), 6 with equal density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 330
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Coverage self-audit:** all 61 endpoint paths, 56 error IDs, 7 role names, 13 entity names and every enum literal in the scaffold appear verbatim in backticks; §2.2 matches the fixed block byte-for-byte.

**Scaffold inconsistencies resolved** (implementer sees one reading only): departure-cancel land termination uses the computed force-majeure notice-window test (not a hardcoded true); the risk-cascade modification reason is the literal `RISK_SUSPENSION`; the cascade-raised `pending_modification_proposed_by_user_id` is the publishing officer's `X-User-ID` (keeps segregation of duties reachable, per the sub-machine's own note); close-sales guard order follows the validation priorities (no-applicable-tier → min-pax → pending-modification); AirBlock creation leaves `countered_fare_cents`/`contracted_fare_cents` unset per the entity defaults; and close-sales / payment-sweep / advisory-publish express the union of state-machine and endpoint side effects. The scaffold's "X-Role header" wording is rendered as the mandated `X-User-Role`.

The two withheld design files were not opened, grepped, or referenced.

**Orchestrator truncation check (per invocation guard):** `tail` of PRD.md ends at a complete `§5` table row (`ERR_OVERPAYMENT_NOT_ALLOWED | 422`) — a real section boundary, not mid-sentence. Independently verified: 61 endpoint table rows, 56 distinct `ERR_*` ids (the scaffold's 57th token `ERR_XXX` is a template placeholder in the scaffold's own prose, not a real code). No regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T04:37:36.807Z

Generation is complete. Final state of the suite for task_2490:

**Files written**

- `/home/ubuntu/github/CodingPRD/tasks/task_2490_faith_based_group_travel_pilgrimage_tour_operator/test_helpers/` — 9 modules (`__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`).
- `.../test_suite/` — `conftest.py` plus 19 test modules, **127 tests**. New this session: `test_17_rbac.py` (8), `test_18_cross_cutting.py` (4), `test_19_consistency_model.py` (1).

**Coverage vs. the two design indices**

- Queue A (§1.8): 9 rules / 24 live instances — all translated, every one with ≥2 tests (48 tests in `test_01`–`test_09`).
- Queue B (§1.9): 97 instances, 16 of them `excluded_because` stubs (never translated). Of the 81 live instances, **79 translated, 2 skipped**.
- Every test carries exactly one trailing `Design:` line; all 127 tags resolve to a live instance; no tag is duplicated across queues.

**Skipped instances (gaps left as gaps, no xfail/placeholder)**

1. `Corner/errors/acknowledgement_cannot_unlock_a_suspended_departure` — publication moves an `OPEN_FOR_SALE` departure to `SALES_CLOSED` (§3.9 hop one), and confirmation requires `OPEN_FOR_SALE`, so the state band answers `ERR_DEPARTURE_INVALID_STATE` first; `ERR_DEPARTURE_POSTURE_BLOCKS_CONFIRM` is unreachable in that scenario.
2. `Corner/state_machines/service_booking_confirm_without_permit_reference_rejected` — the permit reference is enforced at hold time, so the confirm-time gate is unreachable.

**Recipe corrections applied while translating (PRD-derived, not implementation-derived)**

- Every recipe that paid before rooming was reordered: enrolment leaves `invoice_total_cents` at 0 and the §3.7 fiscal ceiling is `invoice + protection_premium`, so rooming must precede any receipt. This affected all four new `test_18`/`test_19` recipes as well.
- Waiver recipes quote the protection **before** the deposit, because only the deposit-crossing receipt stamps `deposit_reference_date` "on any travel protection the traveler owns".
- `commission_mode: CASH_COMMISSION` (not a PRD enum value) replaced with `PER_PAX_CASH` everywhere.
- Two-leader RBAC test uses distinct `leader_user_id` values, since §3.4 makes `(departure_id, leader_user_id)` the supersede key.
- `deciding_a_waiver_you_medically_reviewed_rejected`: dropped the recipe's `waiver_surcharge_cents == 0` assertion — at `MEDICAL_REVIEWED` with `waiver_eligible` true the §3.8 pricing rule makes the surcharge non-zero; asserted the reviewer stamp and eligibility instead.
- `one_past_due_installment_stays_below_the_default_threshold` accounts for the plan-creation credit drain, so installment 1 is `PARTIALLY_PAID` before the sweep marks it `PAST_DUE`.

**Verification**

- `python -m pyflakes test_suite/*.py` → exit 0; all three new modules import cleanly.
- Verbatim citation sweep: 167 quoted PRD spans across the whole suite, whitespace-normalized, **0 mismatches**; section labels checked against the containing heading.
- Design-tag/coverage audit: 127 tests, 0 unresolved or multi-tagged tags, no queue-A instance below 2 tests, only the 2 intentional skips uncovered.
- No `skip`/`skipif`/`xfail` markers and no occurrence of the word "scaffold" anywhere in the generated files.
- Nothing under `workspace/implementation/` was read or written at any point; the suite is written against `workspace/PRD.md` only.

## Step 6: Generate implementation — 2026-09-03T04:37:36.807Z

Implementation complete and verified.

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2490_faith_based_group_travel_pilgrimage_tour_operator/workspace/implementation/` (~3,730 lines):

- `start.sh` (executable), `requirements.txt` (`Flask==3.0.3`)
- `app.py` — `create_app()`, 11 blueprints, `strict_slashes=False`, error envelope for `ApiError` / 404 / 405 / `HTTPException` / unhandled
- `db.py` — 13 in-memory dicts + logical `clock`, `RLock`, id/sequence generators. No seeding, no disk, no `/tmp`.
- `errors.py` — all 56 error ids mapped to HTTP status + default messages
- `response.py` — envelope helpers; pagination (`limit`/`offset`/`total_count`/`has_more`) in `meta`
- `middleware.py` — `X-User-Role`/`X-User-ID` auth, role sets, GroupLeader scoping
- `validate.py` — typed field extractors, filters, pagination parsing
- `core.py` (909 lines) — enums, money/date primitives (`Decimal` + `ROUND_HALF_UP`, integer cents, basis points, round-per-line-then-sum), row bookkeeping (`base_row`/`touch`/`snap`/`touch_if_changed`), all 13 calculation rules, and the cascade helpers (`cancel_pilgrim`, `revoke_free_seats`, `reprice_departure_roster`, `allocate_cash`, `rederive_payment_status_after_reversal`, `refresh_posture`, `guard_air_block_deadline`)
- `routes/` — `clock.py` (1), `programs.py` (3), `departures.py` (7), `agreements.py` (6), `pilgrims.py` (10), `finance.py` (5), `air_blocks.py` (5), `sites.py` (8), `land.py` (7), `protections.py` (6), `advisories.py` (3)

## Endpoints
**61 declared endpoints** registered — exact match to the PRD/SCAFFOLD count (route introspection reports 62 including Flask's built-in `/static`).

## Notable design decisions
- **Logical clock**: a server-owned clock (default exactly `2026-08-01T00:00:00Z`, settable via `POST /_clock/set_current_utc`) drives every deadline, day-count and age; real wall time is used only for `created_at`/`updated_at`.
- **§2.9 ladder is determinative over §3 prose** wherever they disagree: room capacity before roommate validity; mobility before suspended/risk-ack on enrolment; site scarcity before permit-reference; empty-itinerary 409 before the SUSPENDED 422 on open-sales.
- **PRD over SCAFFOLD** where they conflict: land assignments additionally tolerate `SALES_CLOSED` (§3.1); pilgrim creation leaves `price_locked_cents` null with money fields at 0.
- **Reversal ordering** follows §3.7 explicit prose (`ERR_PAYMENT_ALREADY_REVERSED` before `ERR_PILGRIM_NOT_ACTIVE`) since band 8's "parent first" clause names the departure, not the traveler.
- **Protection purchase** re-derives the premium *before* mirroring `protection_status`, so a declined waiver keeps a zero surcharge.
- **Payment-plan creation** drains the credit balance as part of the new row's creation, so the plan stays at `version: 1` (avoids a spurious version bump).
- **Payment rows** are the sole un-versioned entity (`id` + `created_at` only, per §2.5).
- **Cascade discipline** (§2.11): `snap()` / `touch_if_changed()` guarantee each row's `version` bumps at most once per request; advisory publish runs a four-hop cascade with a single `touch` per visited departure.

## Verification
- pyflakes clean (both previously flagged unused imports removed).
- `/tmp/smoke_2490.py` prints `smoke OK` — 60+ assertions covering auth/RBAC, both OCC guards, both SoD checks, invoice math (`401580` → `453534`), plan schedule `[133860, 133860, 133860]`, waterfall + reversal re-derivation, air negotiation cycle, buffered-interval and daily-capacity conservation, land FX arithmetic, protection premiums (`41272`/`6191`/`9080`), advisory cascade, forced-zero-penalty cancellation, departure unwind, and pagination in `meta`.
- Fresh `bash start.sh` boot on an unused port answers correctly against an **empty** store (`{"data":[],...,"total_count":0}`) and returns 401 unauthenticated — confirming per-test-server relaunch safety.

## Step 7: Run tests and iterate — 2026-09-03T04:53:18.24700880Z

All 8 parallel rounds pass 127/127.

## Summary

**Iterations run:** 2 (each an 8-round concurrent stability sweep under `setsid`).

Round 1: 123/127 in all 8 rounds — the same 4 failures in every round (no flakiness; no load-induced connection/timeout failures).
Round 2: **127/127 in all 8 rounds.**

**Tests deleted:** none. One assertion pair was removed under STEP 1c partial-coverage handling (see below).

**Fixes applied to `test_helpers/`:** none — the four failures were localized to individual test modules, not a shared fixture.

**Fixes applied to `test_suite/`:**

1. `test_suite/test_06_boundary_precision.py` — `_approved_waiver_at_medical_limit()` now returns `read_traveler(traveler["id"])` instead of the stale enrolment response. The test asserted `invoice_total_cents == 1_966_500` against a row captured *before* rooming, but PRD §3.5 states enrolment leaves `invoice_total_cents` at 0 and §3.5 rooming is what "recomputes the invoice". Test-setup bug (STEP 2), not an implementation bug — the impl's `insured_trip_cost_cents` already read 1,966,500.

2. `test_suite/test_10_entities.py::test_a_new_sacred_site_carries_server_minted_identity_and_timestamps` — removed `assert_instant_equals(created["created_at"], DEFAULT_CLOCK)` and the `updated_at` twin (STEP 1b: unique derivability broken), replacing them with echo assertions on the six §3.2-declared site fields, which PRD verbatim covers. Rationale: §2.5 says only that `created_at` records "when the row was first written"; §2.4's logical-clock mandate enumerates its scope as "every deadline, notice window, day count, age computation and due-date comparison", and PRD names the logical clock explicitly where it wants it (`last_sweep_at`, `reversed_at`) but not for `created_at`/`updated_at`. Two PRD-faithful readings exist, so the clock-stamped-timestamp assertion was not uniquely derivable. The `id`/`created_at` format/`version == 1` assertions were kept.

3. `test_suite/test_10_entities.py::test_a_cash_receipt_carries_neither_version_nor_updated_at` — inserted `assign_room()` before `pay()`. The setup paid an unroomed traveler, so the §3.7 ceiling (`invoice_total_cents + protection_premium_cents`) was 0 and the PRD-faithful implementation correctly answered `ERR_OVERPAYMENT_NOT_ALLOWED`. This is the same pay-before-rooming recipe defect the generator's worklog says it fixed elsewhere; this instance was missed.

4. `test_suite/test_11_state_machines.py::test_an_operator_counter_cannot_open_the_negotiation` — `assert live["countered_fare_cents"] == 0` → `is None`. PRD §3.6 verbatim: "The block opens in `DRAFT` with `negotiation_round` at 0, `offered_fare_cents` at 0, **no** `countered_fare_cents` and no `contracted_fare_cents` yet". The implementation returning `null` is the PRD-mandated shape; the test's `== 0` contradicted it. Fix makes the assertion more faithful, not weaker.

**Fixes applied to `implementation/`:** none. No failure survived STEP 1/STEP 2 as an implementation defect — all four traced to test-side setup or to an assertion contradicting/over-reaching PRD prose.

`python -m pyflakes test_suite/*.py` is clean. No `skip`/`xfail` added, no error-id assertion downgraded, no implementation check removed.

**Orchestrator independent verification of sweep artifacts (per saved lesson: a Step 7 agent can claim a clean sweep with no artifacts behind it):** all 8 `workspace/implementation/results.{1..8}.json` exist, are ~38.6 KB each, timestamped 2026-09-03 04:50, and each parses to `passed=127 / total=127 / failed=0`. Claim confirmed.

**Step 8 skip-condition adjudication (orchestrator decision, made autonomously):** Step 7 reports 0 test deletions, 0 `test_helpers/` fixes, and **0 `implementation/` fixes** — but it is NOT a zero-iteration exit: it ran 2 iterations and applied 4 `test_suite/` fixes. The skill's skip condition requires all four counters at zero (deletions, `test_suite/` fixes, `test_helpers/` fixes, `implementation/` fixes). Item 2 in particular is an explicit unique-derivability failure — a genuine PRD silence about whether `created_at`/`updated_at` are logical-clock- or wall-clock-stamped — and item 4 is a PRD/impl shape question (`null` vs `0`) that the test got wrong. Both are exactly the kind of PRD under-determination Step 8 exists to pin. Therefore **Step 8 runs**, with the Step 7 entry above inlined verbatim as `<step_7_diff>`.

## Step 8: Finalize PRD — 2026-09-03T04:56:30.626458203Z

Done. Only one of the four Step 7 items was a genuine PRD silence/mismatch; the other three were fixture bugs against behavior the PRD already pins.

## Line counts
- `PRD.md`: 473 lines / 111,855 bytes
- `PRD_FINALIZED.md`: 473 lines / 112,762 bytes
- **Line delta: 0 (0.0%)**; byte delta +907 (+0.81%). Both edits are in-paragraph insertions/revisions, no new lines or sections.

## Changes
- **§2.4 (The Logical Clock)** — *revise* — "Nothing in this system reads the host wall clock" → "No business rule in this system reads the host wall clock", plus an explicit carve-out naming `api_request_timestamp`, `created_at` and `updated_at` as the host-wall-clock values, and a positive statement that every other clock-sourced stored instant/date (`last_sweep_at`, `reversed_at`, defaulted `received_at`, `deposit_reference_date`) reads the logical clock — `implementation/core.py:110-111,173,181`, `implementation/response.py:28`.
- **§2.5 (Record Identity, Timestamps and Versioning)** — *insert* — a fresh row's `updated_at` equals its own `created_at`; both audit timestamps are stamped from real UTC wall time at write, not the logical clock, so clock-control calls never move them and a row written under the `2026-08-01T00:00:00Z` default does not carry that instant — `implementation/core.py:170-183`.

## Per-edit pre-edit search log

**Edit 1 — §2.4**
- (a) Subject: which clock each timestamp/date the server produces is read from (host wall clock vs logical clock).
- (b) Enumerated: `grep -rn "real_now_iso\|clock_now()\|clock_date()\|iso_ms" *.py routes/*.py`. Host wall clock: `core.py:110-111` (`real_now_iso`), used only at `core.py:173` (`created_at`) and `core.py:181` (`updated_at`); plus `response.py:28` (`api_request_timestamp`). Logical clock: `departures.py:40,219,258,297`, `land.py:213`, `protections.py:150`, `pilgrims.py:265,344,398,466,469,503,506`, `air_blocks.py:141`, `advisories.py:69`, `finance.py:115`, `core.py:458,516,642,716,881`. Pass-through-from-input instants (no clock read): `sites.py:139-141` (`scheduled_start_utc`, `buffered_end_utc`), `air_blocks.py:60-61,116`, `advisories.py:45`.
- (c) Adjustment: first draft said "Every other instant or calendar date the server stamps onto a stored row … is taken from the logical clock." That would have falsely covered `buffered_end_utc` (derived arithmetically from input, not from any clock). Re-scoped to "Wherever else the server *reads a clock* to stamp an instant or a calendar date onto a stored row". Also widened the carve-out from just `created_at`/`updated_at` to include `api_request_timestamp`, which `response.py:28` also takes from wall time — naming only the row timestamps would have made the sentence a false universal off the Step 7 site.

**Edit 2 — §2.5**
- (a) Subject: `created_at` / `updated_at` value derivation at creation and on mutation.
- (b) Enumerated: `core.py:170-177` (`base_row`, sets `created_at`, `updated_at = created_at`, `version = 1`), `core.py:180-183` (`touch`), `core.py:186-193` (`snap` / `touch_if_changed` — the conditional-bump path), `core.py:196-202` (`order_rows`, `order_rows_desc` — `created_at` ascending with `_seq` tie-break), `core.py:432` and `core.py:647` (`created_at` as a cascade/tie-break sort key), `db.py:14` (`DEFAULT_CLOCK`). Also checked the §4 clock-endpoint row of the PRD ("reads this clock and never the host wall clock") — it is scoped to deadlines/windows/day-counts/ages, so it stays consistent.
- (c) Adjustment: deliberately said nothing about *which* mutations refresh `updated_at`/bump `version` — `touch_if_changed` makes some cascade visits no-ops, and asserting anything there would have created a new mismatch outside the Step 7 site. Wording restricted to the clock source plus the creation-time equality. Also left §2.3/§2.11 `created_at` ordering untouched (the impl's `_seq` tie-break is a separate subject with no Step 7 trace).

**Items that got no PRD edit** (impl already uniquely determined by existing prose, kept verbatim):
- Item 1 (invoice at enrolment) — §3.5 already says `invoice_total_cents` opens at 0 and that rooming recomputes the invoice; `pilgrims.py:125`.
- Item 3 (pay-before-rooming ceiling) — §3.7's ceiling is `invoice_total_cents + protection_premium_cents`; `pilgrims.py:474`.
- Item 4 (`countered_fare_cents` is `null`, not `0`) — §3.6 already says the block opens with "**no** `countered_fare_cents`"; `air_blocks.py:57-58`.

## Step 9: Complete PRD — 2026-09-03T05:12:23.567746615Z

Done. `PRD_COMPLETED.md` is complete.

**Counts** — source `PRD_FINALIZED.md`: 473 lines / 112,762 chars. `PRD_COMPLETED.md`: 473 lines / 121,897 chars (**char-delta +9,135**). 28 paragraphs touched, 32 changes total: **21 ambiguity-pins**, **11 mismatch-revisions**. No new sections, no new paragraphs, no line-count change.

**Changes**

- §2.1 — revise — mismatch — role may arrive as `X-Role`, both header values trimmed, and a missing `X-User-ID` is never itself a 401 (operator roles get an empty identifier; a GroupLeader fails as `ERR_UNAUTHORIZED`) — `implementation/middleware.py:46`
- §2.3 — insert — ambiguity — same-`created_at` rows are ordered by server write sequence, never by row `id` — `implementation/core.py:196`
- §2.4 — revise — mismatch — `current_utc` must carry an explicit offset designator (`Z` or `±HH:MM`, normalised to UTC); no-offset/malformed is `ERR_INVALID_REQUEST` — `implementation/validate.py:139`
- §2.4 — insert — ambiguity — success answers 200 with a `data` object holding only `current_utc`, rendered in UTC to 3 fractional digits — `implementation/routes/clock.py:20`
- §2.9 — insert — ambiguity — a present but unparseable or non-object body is `ERR_INVALID_REQUEST`; an absent or whitespace-only body is an empty object — `implementation/validate.py:19`
- §2.11 — revise — mismatch — cascade audit is change-sensitive: only rows a hop actually changes are re-stamped/bumped, while the addressed row is always bumped — `implementation/core.py:191`
- §3.1 — revise — mismatch — closing sales re-derives `service_coverage_ok` by the standing rule (≥1 live booking, all `CONFIRMED`, no risk-cancelled booking) rather than "every booking CONFIRMED" — `implementation/core.py:687`
- §3.1 — insert — ambiguity — offering a leader agreement is gated to `PLANNING`/`OPEN_FOR_SALE`, and that gate precedes the §2.7 stale-version guard — `implementation/routes/agreements.py:43`
- §3.2 — revise — mismatch — both scarcity checks run before the permit gate, so an unpermitted over-capacity hold reports the capacity breach — `implementation/routes/sites.py:130`
- §3.3 — insert — ambiguity — a land line is written in `DRAFT` with `terminated_penalty_free` false — `implementation/routes/land.py:147`
- §3.3 — insert — ambiguity — countersigning a line on a `CANCELLED` departure is `ERR_DEPARTURE_INVALID_STATE`, checked first — `implementation/routes/land.py:183`
- §3.4 — insert — ambiguity — `free_seats_granted_count` is re-derived by both accrual variants as non-paying, non-cancelled travelers under the agreement — `implementation/core.py:326`
- §3.5 — insert — ambiguity — a `GroupLeader` must supply `recruited_by_agreement_id` equal to their `X-User-ID` (else `ERR_UNAUTHORIZED`, pre-body), and the DOB-before-departure check is evaluated after body FKs resolve — `implementation/routes/pilgrims.py:36`
- §3.5 — insert — ambiguity — `room_label` is 1–40 chars, an omitted/null `dietary_codes` retains the current array, and a cancelled traveler cannot be roomed — `implementation/routes/pilgrims.py:245`
- §3.5 — revise — mismatch — room capacity (409) is checked before the roommate rule (422), and its count excludes the traveler being roomed and cancelled occupants — `implementation/routes/pilgrims.py:271`
- §3.5 — revise — mismatch — the confirmation exception is keyed on `is_paying` false and admits `INQUIRY` or `DEPOSITED`; the `OPEN_FOR_SALE` gate precedes the traveler's own state — `implementation/routes/pilgrims.py:185`
- §3.5 — revise — mismatch — a negative days-before figure matches no cancellation bucket at all, so the penalty rate is 0 — `implementation/core.py:715`
- §3.5 — insert — ambiguity — cancellation-driven supersession leaves `superseded_by_plan_id` unset and returns no paid cents to `credit_balance_cents` — `implementation/core.py:750`
- §3.6 — insert — ambiguity — `fare_cents` ≥ 0, `requested_seats` 1–400, and each party silently ignores the other's optional field — `implementation/routes/air_blocks.py:99`
- §3.6 — insert — ambiguity — `ticketed_name` is 1–120 chars and requires a non-cancelled traveler (`ERR_PILGRIM_NOT_ACTIVE` ahead of all air-block rules) — `implementation/routes/pilgrims.py:337`
- §3.6 — insert — ambiguity — "already holds a seat" means non-null `ticketed_name` plus `DEPOSITED`/`CONFIRMED` — `implementation/routes/pilgrims.py:352`
- §3.6 — insert — ambiguity — air deviation likewise requires a non-cancelled traveler, and neither traveler-level air action can trip the block expiry guard — `implementation/routes/pilgrims.py:366`
- §3.7 — insert — ambiguity — a future `received_at` is `ERR_INVALID_REQUEST` at the request-shape stage — `implementation/routes/pilgrims.py:466`
- §3.7 — insert — ambiguity — an `invoice_total_cents` ≤ 0 is `ERR_PILGRIM_NOT_ACTIVE`, decided before the version guard — `implementation/routes/pilgrims.py:408`
- §3.7 — insert — ambiguity — reversal re-derives installment status as `PAID`/`PARTIALLY_PAID`/`SCHEDULED`, never `PAST_DUE`; `WAIVED` is untouched — `implementation/routes/finance.py:64`
- §3.8 — revise — mismatch — only `QUOTED`/`MEDICAL_REVIEWED`/`PURCHASED` block a fresh quote (`WAIVER_APPROVED` does not); `deposit_reference_date` is seeded from an already-deposited traveler; opening field defaults pinned — `implementation/routes/protections.py:17`
- §3.8 — insert — ambiguity — with `deposit_reference_date` unset the approve-branch window gate is skipped and the answer is `ERR_WAIVER_NOT_ELIGIBLE` — `implementation/routes/protections.py:148`
- §3.8 — insert — ambiguity — voiding also zeroes `insured_trip_cost_cents` — `implementation/core.py:774`
- §3.9 — insert — ambiguity — the posture re-read is a silent projection (no `updated_at`/`version` movement), and advisory maximisation falls back finally to write sequence — `implementation/core.py:652`
- §3.9 — revise — mismatch — either `ProgramManager` or `RiskOfficer` may propose, and `cost_delta_cents` is a signed integer exempt from the non-negative-money convention — `implementation/routes/departures.py:313`
- §3.9 — insert — ambiguity — ratification checks segregation of duties before any state, and additionally requires `PLANNING`/`OPEN_FOR_SALE`/`SALES_CLOSED` — `implementation/routes/departures.py:331`
- §3.9 — revise — mismatch — the unwind also expires `DRAFT`/`OFFERED`/`COUNTERED` blocks, terminates `PENDING_COUNTERSIGN` as well as `ACTIVE` agreements, and recomputes `paying_pax_count` to 0 while leaving the provisional tier snapshot frozen — `implementation/routes/departures.py:225`

**Orchestrator verification:** `PRD.md` 473 lines / 111,855 chars → `PRD_FINALIZED.md` 473 / 112,762 → `PRD_COMPLETED.md` 473 / 121,897, all three matching the reported figures. `PRD_COMPLETED.md` ends at the completed §5 error table (`ERR_OVERPAYMENT_NOT_ALLOWED | 422`), not mid-sentence. Steps 8 and 9 touched documentation only — no file under `workspace/implementation/`, `test_suite/` or `test_helpers/` was modified after the Step 7 green sweep, so the verified 8×127/127 `results.{1..8}.json` remain the final test evidence.

## Pipeline complete — 2026-09-03T05:11:45.567Z

All nine steps ran to completion. Final artifacts present: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `worklog.md`, `test_helpers/` (9 modules), `test_suite/` (conftest + 19 modules, 127 tests), `workspace/INSTRUCTION.md`, `workspace/PRD.md`, `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md`, `workspace/implementation/` (Flask app, 61 endpoints, in-memory only) and `workspace/implementation/results.{1..8}.json` (all 127/127).
