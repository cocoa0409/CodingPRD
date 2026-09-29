# Worklog — task_2107_sponsorship_inventory_activation

## Step 1: Create Task Directory — 2026-08-16T03:43:15.728Z

Created `tasks/task_2107_sponsorship_inventory_activation/` and `tasks/task_2107_sponsorship_inventory_activation/workspace/` (index 2107 = highest existing 2106 + 1).

## Step 3: Copy Shared Files — 2026-08-16T03:43:40.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2107_sponsorship_inventory_activation/workspace/INSTRUCTION.md` (1424 bytes).

## Step 2: Generate Scaffold — 2026-08-16T05:08:30.000Z

All three artifacts are generated, lint-clean, and cross-verified. Final linter run:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    43
  §1.1 entities declared:     12
  §1.8 instances scanned:     22
  §1.9 instances scanned:     38
  Calls scanned (§1.8+§1.9):  993

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5
and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was generated

**`SCAFFOLD.yaml`** (§1.0–§1.7, 2092 lines)
- **Profile**: `quota_allocation` + `temporal_windowing`; layers = optimistic concurrency, cascading side effects, dual-variant calculation, derived-field reconciliation; topology `graph` (junctions Entitlement + StaffAssignment, self-referential RateCard supersession); shape `cyclic` (+ parallel dimension); role model `segregation_of_duties`; `api_prefix: "/"` (flat top-level collections). Expert-plus band.
- **12 entities**: Property, RateCard, RateCardLine (immutable), InventoryAsset, Sponsor, Contract, Entitlement, AssetBooking, ProofOfPerformance, StaffMember, StaffAssignment, SponsorSurvey (immutable). 16 canonical `FK -> X.id` declarations, all reverse-reachable.
- **8 state machines** (7 entities; Contract carries two dimensions): Property linear-guarded; RateCard DRAFT->PUBLISHED->SUPERSEDED; Contract cyclic SUBMITTED<->DRAFT (revision_round capped at 3) **plus** an independent `fulfillment_status` axis; Entitlement compound; AssetBooking branching (DELIVERED/CANCELLED/PREEMPTED); ProofOfPerformance branching (VERIFIED/REJECTED with disjoint effects); StaffAssignment conditional-cascade.
- **2 concurrency rules** (OCC only): `booking-create-stale-asset` (InventoryAsset.version, 412) and `countersign-stale-property` (Property.version, 412).
- **8 calculations**: entitlement_unit_valuation (tiered, mode a), contract_value_rollup (pinned evaluation order, mode c), in_kind_recognized_valuation (**dual variant** CONSERVATIVE/AUDITED), delivery_rollup, makegood_credit_allocation (waterfall, floor-then-remainder, mode b), renewal_likelihood_scoring (**dual variant** SURVEY_WEIGHTED/DELIVERY_ONLY), roi_roo_report (**dual variant** VERIFIED/GROSS), property_inventory_rollup.
- **17 ordered validations** (auth -> ownership -> schema -> existence -> state -> clock gates -> OCC -> SoD -> exclusivity -> referential -> interval bounds -> overlap/buffer/rest-gap -> capacity/uniqueness -> fiscal ceiling).
- **43 endpoints** (incl. `POST /_clock/set_current_utc`, default clock pinned to `2026-08-01T00:00:00Z`), **44 error codes**, **6 roles** (5 opaque + `SponsorContact` = `entity_backed:Sponsor`).

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — 22 instances across all 9 rule_ids (2/3/3/2/3/3/2/2/2), every chain executable from empty DB. All formula-derived asserts were computed in Python (e.g. unit_value 337500 vs 375000 at the tier boundary; in-kind 776250 -> 504563 across variants; makegood split 435278/85120 from pool 520398 where half-up rounding would wrongly give 435277/85121; renewal 51.25/MEDIUM -> 72.25/HIGH; ROI 0.3478 with CPM 7762.50 vs 5544.64).

**`SCAFFOLD_CORNER_DESIGN.yaml`** — 47 instances (38 with full recipes + 9 `excluded_because` stubs) over all nine claim-extraction sections: entities 9, state_machines 7, calculations 4, validations 7, endpoints 2, rbac 5, cross_cutting_layers 4, errors 8, consistency_model 1.

## Verification performed
- `scaffold_lint.py` clean (checks a-f).
- Custom audit: 0 unbound `${var}` across 993 calls, 0 duplicate instance names (69 total), all `grounds:` refs resolve, all 44 error codes referenced outside the catalog, all 43 endpoints exercised by at least one recipe, all stub `difficulty_instance` references resolve, no forbidden concurrency vocabulary, and every OCC `expected_*_version` sourced from a fresh `captures:`.
- Two arithmetic defects found and fixed during self-review (a mis-tiered `cash_value_cents` of 3456000 -> 3312000, and a weak stub replaced by a real OCC instance).
- Constraint honored: no sibling `tasks/task_*/` directory was listed, read, or searched.

## Step 4: Generate PRD — 2026-08-16T05:22:00.000Z

PRD generated at `workspace/PRD.md` — **352 lines / ~10,150 words**. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, and no sibling task directory was read.

## Section structure

- **§1 Introduction** — 3 paragraphs (inventory-as-conserved-quantity, dual-fidelity revenue recognition, execution/segregation-of-duties angle)
- **§2 Global Specifications** — 10 subsections: 2.1 Access Control and Operator Identity · 2.2 API Response Structure (verbatim from `section-2.2-response-structure.md`, byte-verified) · 2.3 Pagination · 2.4 Resource Identity, Audit Fields and Versioning · 2.5 The Season Clock · 2.6 Money, Percentages and Rounding Discipline · 2.7 Version Guards on Shared Inventory and Pricing · 2.8 Path Resolution and the Order of Rejection (17-rung priority ladder) · 2.9 Cascade Integrity Across the Sponsorship Graph · 2.10 Segregation of Duties
- **§3 Business Logic** — 9 subsections along the commercial timeline: 3.1 Property/season envelope · 3.2 Rate cards & publication · 3.3 Inventory estate · 3.4 Sponsors, draft contracts, entitlements · 3.5 Submission/revision/countersignature · 3.6 Bookings & conflict geometry · 3.7 Staffing & shift execution · 3.8 Delivery, proof capture, adjudication · 3.9 Termination, close-out, renewal scoring, ROI/ROO
- **§4** 43-row endpoint table (4 columns) · **§5** 44-row error table (2 columns). Document ends at §5 with no audit footer.

## Hard Contract reports

```
Field coverage check:
- entities[].fields: 81 required, 81 present, 0 missing
- endpoints[].request_body: 54 required, 54 present, 0 missing
- endpoints[].query_params: 14 required, 14 present, 0 missing
- endpoints[].path_params: 1 required, 1 present, 0 missing
- nested/output identifiers (tier_breaks keys, roi-report shape, clock): 10 required, 10 present, 0 missing
Status: PASS   (two independent passes, exact-backtick matching, 99 identifiers)
```
```
Rule coverage check:
- validations[] with priority: 17 checked, 17 expressed in prose (explicit §2.8 ladder + per-workflow orderings in §3.1/3.5/3.6/3.7/3.8/3.9), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_inventory_asset_version / expected_property_version + ERR_ASSET_VERSION_STALE / ERR_PROPERTY_VERSION_STALE + 412), 0 missing
- state_machines[].transitions: 7 machines / 33 transitions checked, 33 fully expressed (from/to named, every precondition paired with its error_id, every side effect stated incl. multi-hop cascades), 0 missing
- calculations[]: 8 checked, 8 fully expressed in prose incl. all 3 dual-variant pairs (CONSERVATIVE/AUDITED, SURVEY_WEIGHTED/DELIVERY_ONLY, VERIFIED/GROSS), 0 missing
- validations[] conditions: 44 error ids checked, 44 matchable to a condition in §2/§3 narrative, 0 missing
- endpoints[].side_effects / applies_to: 43 endpoints checked, all side-effect sets and applies_to scopes expressed, 0 missing
- entities[].fields[] structured content: 81 checked (type, default, initial value, constraint range, common_fields exceptions), 81 reconstructible, 0 missing
- sibling-branch symmetry: 9 groups checked (proof VERIFIED/REJECTED, booking DELIVERED/CANCELLED/PREEMPTED, contract terminate from COUNTERSIGNED/ACTIVE, entitlement ->SHORTFALL and ->WAIVED pairs, assignment ->NO_SHOW/->RELEASED, 3 calculation variant pairs), 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 752
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Coverage audit vs. §1.1–§1.7

- **§1.1 Entities (12):** all present with defaults/ranges. `RateCardLine` and `SponsorSurvey` are explicitly called out in §2.4 and §3.9 as carrying only `id` + `created_at` (no `updated_at`, no `version`).
- **§1.2 State machines (7):** Property PLANNING->SELLING->IN_SEASON->CLOSED with unconditional rejection of skips/reversals; RateCard DRAFT->PUBLISHED->SUPERSEDED with the supersession cascade and pin-survival; Contract lifecycle including the capped SUBMITTED<->DRAFT revision loop; Contract `fulfillment_status` as an independent second dimension; Entitlement compound status; AssetBooking 3-way branching fork; ProofOfPerformance disjoint fork; StaffAssignment.
- **§1.2.1 Concurrency (2):** both OCC rules framed purely in stale-version terms (no "simultaneously"/"race" framing), with mandatory-field, mismatch-rejection, error id and 412 all stated; §2.7 also states no other endpoint takes a version field.
- **§1.3 Calculations (8):** every constant embedded in business context — volume tiers 5,000,000/2,500,000/1,000,000 cents at 0.12/0.08/0.04, in-kind cap 0.25, haircuts 0.50/0.40/0.35/0.20, makegood 0.15, intent adjustments +10/0/-15, bands 70/40, oversell 1.10, rest 45 minutes. Pinned rounding/evaluation orders (round-per-unit-then-multiply; floor-each-share-then-remainder-to-largest; cap-vs-haircut ordering) are all stated as contractual. No pseudocode, no operator syntax, no fuzzy words (verified by regex sweep).
- **§1.4 Validations (17):** §2.8 gives the full ordered ladder; each `applies_to` set is enumerated at its workflow.
- **§1.5 Endpoints (43):** table matches scaffold paths and per-endpoint role sets exactly (verified programmatically, 0 mismatches).
- **§1.6 Errors (44):** all in the §5 table with correct HTTP status; every id also appears with its trigger condition in §2/§3 narrative.
- **§1.7 RBAC (6 roles):** all named verbatim; the five `opaque` identities and the `entity_backed:Sponsor` identity for `SponsorContact` are both translated into explicit §2.1 prose, including scope enforcement across all five sponsor-scoped operations.

## Step 6: Generate Implementation — 2026-08-16T05:45:00.000Z

The implementation is complete and verified.

## Files written

All under `workspace/implementation/` (~2,560 lines, 20 Python modules):

- `start.sh` (executable) — guarded `pip install` (no-op when Flask present), `exec python3 app.py`, foreground, `0.0.0.0:$PORT` (default 10000)
- `app.py` — blueprint registration, error handlers, a WSGI lock that applies each request atomically (protects the conserved-quantity invariants)
- `db.py` — in-memory dicts only, graph navigation helpers, `new_row`/`touch`/`set_fields` audit-field machinery, logical clock seeded to the PRD constant `2026-08-01T00:00:00Z`
- `util.py` — `Decimal`/`ROUND_HALF_UP`/`ROUND_FLOOR` rounding, ISO-8601 3-fractional-digit formatting, all request-shape validators
- `errors.py`, `response.py`, `middleware.py` — 44-entry error catalogue, `meta`/`response_type`/`data` envelope, auth + RBAC + sponsor scoping
- `routes/` — `properties`, `rate_cards`, `inventory_assets`, `sponsors`, `contracts`, `entitlements`, `bookings`, `proofs`, `staff`
- `services/` — `calc.py` (8 calculation rules incl. both dual-variant pairs), `cascade.py` (delivery/contract/property rollups, staffing releases, renewal scoring), `serialize.py`

## Coverage

**43 of 43 endpoints** implemented — verified by enumerating the Flask URL map against the PRD §4 table (exact match, including `/_clock/set_current_utc`).

## Key PRD-fidelity decisions (PRD prose over scaffold structure)

- Submit gate order is PRD §3.5's (property -> entitlements -> revision), not the scaffold's
- Countersign runs the PRD's fixed ladder: state -> published card -> OCC -> SoD -> exclusivity -> rate line -> money -> oversell ceiling
- Rounding orders pinned: per-unit value rounded *before* multiplying; CONSERVATIVE = haircut-then-cap, AUDITED = cap-then-haircut; makegood floors *each* share then hands the whole remainder to the largest bucket
- Input datetimes are echoed verbatim; `published_at`/`delivered_at`/`current_utc` echo the logical clock's raw form; `created_at`/`updated_at` are wall-clock with 3 fractional digits (keeps `created_at ASC` tie-breaks and list ordering deterministic)
- ROI report excludes proofs on `CANCELLED`/`PREEMPTED` bookings, per the PRD's "under neither basis does a CANCELLED or PREEMPTED booking ever count"
- Rate-card lines and sponsor surveys carry `id` + `created_at` only — no `version`, no `updated_at`

## Verification

Three hand-written smoke suites (~130 assertions) all pass: full happy path with hand-computed money (unit 150000 -> gross 7.5M -> 12% discount -> cash 6.6M -> in-kind 1.3M -> total 7.9M), supersession, exclusivity conflict, oversell ceiling, revision-loop cap, changeover buffer + same-contract exemption + capacity, staff 45-minute rest and closed-interval collision, staffing gate, proof-rejection cascade unwinding four rows, termination cascade, makegood waterfall, pagination/ordering, ladder precedence, both in-kind variants, both ROI bases, renewal target selection and churn.

**Boot confirmed**: three consecutive kill/relaunch cycles via `bash start.sh` — ready in ~0.68 s each, HTTP 200, and `total_count=0` after each restart despite entities created in the prior round, proving no seeding and no carry-over state. `pyflakes` is clean.

## Step 5: Generate Unit Tests — 2026-08-16T06:05:00.000Z

Test infrastructure and suite generated for `task_2107_sponsorship_inventory_activation`.

## Files written

**`test_helpers/`** (9 files, ~2,200 lines)
- `types.py` — 19 status enums + entity TypedDicts. `RateCardLine` and `SponsorSurvey` correctly omit `updated_at`/`version` (write-once resources).
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (43 endpoints incl. `/_clock/set_current_utc`).
- `api_errors.py` — 44-value `ApiErrorId` enum + HTTP status map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions, `assert_write_once_fields`, `assert_whole_cents`, `assert_instant_equals`, `assert_reserved_units_total`, `assert_contract_money_consistency`, `assert_roi_report`.
- `factories.py`, `constants.py`, `test_users.py` (incl. `make_sponsor_contact_headers(sponsor_id)` for the one `entity_backed` role), `fixtures.py` (~800 lines, 5 tiers: primitives -> estate -> lifecycle stage walker -> multi-contract properties -> staffing/evidence/close-out scaffolds), `__init__.py` barrel.

**`test_suite/`** — `conftest.py` + 10 domain-named test files.

## Counts

| | |
|---|---|
| Tests emitted | **82** (all collect cleanly) |
| Queue A (Difficulty) | **44 tests / 22 instances** — every instance >= 2 tests |
| Queue B (Corner) | **38 tests / 38 non-stub instances** — every instance >= 1 test |
| `excluded_because:` stubs | **9** — all cross-references resolve to real difficulty instances; none translated |

## Verification performed (all clean)

- Every test docstring ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line, resolving to a real instance.
- Every quoted PRD citation (>=8 words) survives a whitespace-normalized literal match against `workspace/PRD.md` — **0 non-verbatim citations**.
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere.
- No "scaffold"/table references leak into generated comments or docstrings.
- pyflakes clean.

## Instances skipped

**None.** All 22 difficulty and all 38 non-stub corner instances passed the PRD-first two-condition filter.

## Two sub-assertions dropped inside otherwise-translated instances

These are unobservable through the PRD's declared endpoint surface, not PRD gaps:

1. **`StaffMember.scheduled_minutes`** assertions (appear in `deliver_blocked_until_staff_assignment_is_checked_in`, `staff_closed_interval_shift_with_forty_five_minute_rest_gap`, `terminate_contract_cascades_...`, `cancel_booking_releases_assignment_and_reserved_units`). The PRD declares **no `GET /staff-members/{id}` endpoint** and no staff-member list, so the field is only readable in the creation response. All other assertions of those instances are asserted.
2. **`delivered_at` exact string** (`2026-09-10T21:00:00.000Z`). PRD §2.5 pins the *instant* ("the clock reading at the moment the write occurred") but not the fractional-digit rendering for system-stamped instants, so the test asserts instant equality via `assert_instant_equals` rather than byte equality — two PRD-only implementers could legitimately emit `...:00Z` or `...:00.000Z`.

## Step 7: Run Tests and Iterate — 2026-08-16T06:20:00.000Z

All 8 parallel rounds pass 82/82. Exiting with the summary.

## Summary

**Iterations run:** 2

Iteration 1 -> 80/82 in all 8 rounds (2 deterministic failures, identical across every round — no flakiness anywhere in the suite). Iteration 2 -> **82/82 in all 8 rounds, union of failures empty.**

**Tests deleted:** none. Both failures survived STEP 1 — each asserted a rule quoted verbatim from PRD §3.5 ("The starting unit price is that line's `base_unit_price_cents`"; "The exclusivity factor is the line's `exclusivity_multiplier` when the contract's `exclusivity_scope` is `CATEGORY`, and 1.00 otherwise"; "the tiered unit price multiplied by the property's `seasonality_index` and by that exclusivity factor, rounded half up to a whole cent"), and PRD pins the evaluation order explicitly, so the outcome is uniquely derivable. Both were STEP 2 test bugs.

**Root cause (single, shared):** `test_helpers/factories.py::create_rate_card_line_payload` defaults `tier_breaks` to a break at `min_units: 10 -> 225,000` and `exclusivity_multiplier` to `1.25` — values calibrated for the 250,000 `DIGITAL_BOARD` line. Two line specs overrode only `asset_class` and `base_unit_price_cents`, silently inheriting both and repricing the clause.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `setup_staffed_booking`, its `ACTIVATION_SPACE` line spec: state `tier_breaks: []` and `exclusivity_multiplier: 1.00` explicitly. The leaked 1.25 premium made the clause price 225,000/unit -> `cash_value_cents` 450,000, contradicting the test's own documented arithmetic (150,000 x 1.20 x 2 = 360,000).

**Fixes applied to `test_suite/`:**
- `test_suite/test_10_version_guards.py` — both Card A and Card B line specs made explicit the same way. This one was more than an arithmetic slip: with the leaked break at `min_units: 10` and a 10-unit entitlement, Card A (base 250,000) and Card B (base 300,000) **both** tier down to the same 225,000, so the money assertion could no longer distinguish which card the countersign pinned — the exact thing the test exists to prove. Restoring the plain lines makes Card B yield 3,312,000 and Card A 2,760,000, so the assertion discriminates again.

**Fixes applied to `implementation/`:** none. The implementation was PRD-faithful on both counts and is byte-identical to its pre-sweep state (verified by mtime); no check was removed or weakened, and no assertion was downgraded, skipped, or xfailed.

Two things worth flagging for whoever owns this task next: the suite contains no concurrency/threading tests, and `db.ordered()` tie-breaks on `(created_at, _seq)` with an in-memory monotonic sequence — so there is no timing- or ordering-sensitive surface for flakiness to hide in, which is consistent with the 8/8 identical results in both sweeps. The latent hazard that caused this remains live, though: `create_rate_card_line_payload` will keep injecting a 10-unit break and a 1.25 premium into any future under-specified line spec. I fixed the two call sites rather than the factory default, since three currently-passing tests in `test_02`/`test_03` call it bare and hardening the default would have changed their inputs; a follow-up that makes the default neutral and updates those call sites would close it off permanently.

## Step 8: Finalize PRD — 2026-08-16T06:30:00.000Z

`workspace/PRD_FINALIZED.md` written — **byte-identical to PRD.md**. No edit was warranted.

## Line counts

| File | Lines | Delta |
|---|---|---|
| PRD.md | 351 | — |
| PRD_FINALIZED.md | 351 | 0 lines, **0.00%** (md5 identical) |

## Changes

None. Zero edits.

## Enumeration log

Both `<step_7_diff>` items share one subject, so one enumeration covers both.

**(a) Subject identified.** Entitlement unit valuation at countersignature — the interaction of `base_unit_price_cents`, `tier_breaks`, `exclusivity_multiplier`, `seasonality_index` and the pinned rounding order (PRD §3.5), plus the creation-time defaults for `tier_breaks` and `exclusivity_multiplier` on a rate-card line (PRD §3.2). Item 1 (`fixtures.py` `ACTIVATION_SPACE` spec) and item 2 (`test_10_version_guards.py` Card A / Card B specs) both broke because the factory's `DIGITAL_BOARD` defaults leaked into specs that overrode only `asset_class` / `base_unit_price_cents`.

**(b) Impl paths enumerated** (grepped `entitlement_unit_valuation|tiered_unit_price|unit_value_cents|exclusivity_multiplier|tier_breaks|seasonality_index` across all of `implementation/`, then read each hit):

- `services/calc.py:31-38` `tiered_unit_price` — sorts breaks ascending by `min_units`, each break with `min_units <= promised_units` overwrites the running price (highest reached wins, boundary inclusive); no break reached leaves the base standing. Exactly PRD §3.5.
- `services/calc.py:41-46` `entitlement_unit_valuation` — `excl = line.exclusivity_multiplier` iff `exclusivity_scope == "CATEGORY"` else `1.00`; `rhu_int(price x seasonality x excl)` then `x promised_units` with no second rounding. Exactly PRD §3.5's pinned order.
- `routes/contracts.py:259-262` — the **sole** callsite of `entitlement_unit_valuation`, inside countersign; prices every entitlement off `by_class[ent.asset_class]` on the pinned card.
- `routes/contracts.py:165` — `unit_value_cents` initialized to 0 at entitlement creation; `:276` the only write. Verified no re-pricing anywhere else: `routes/contracts.py:344-399` (close) re-values only the in-kind leg and makegood, never `unit_value_cents`, `gross_entitlement_value_cents`, `volume_discount_pct` or `cash_value_cents` — matching PRD §3.9. `services/calc.py:93` (makegood shortfall), `services/cascade.py:84` (delivered media value) and `routes/contracts.py:476` (ROI media value) are all pure readers.
- `routes/rate_cards.py:83-85, 108-131` — `tier_breaks` absent -> `[]`; `exclusivity_multiplier` absent -> `Decimal("1.00")`; <=5 entries, distinct `min_units`, both sub-fields int >= 1. Exactly PRD §3.2.
- `routes/properties.py:40-41` — `seasonality_index` default `1.00`, range 0.50–2.00, <=2 dp. Exactly PRD §3.1.
- `services/serialize.py:31-32, 105` — line output carries `id`/`created_at` only, no `updated_at`/`version`; matches PRD §2.4.
- `routes/contracts.py:224-231, 279` — the card the countersign pins (`len(published) != 1` -> `ERR_NO_PUBLISHED_RATE_CARD`; `rate_card_id = published[0].id`) and `routes/rate_cards.py:155-167` (publish supersedes the prior card and bumps the property `version`), which is what test_10 exercises. Both already pinned verbatim by PRD §3.2, §3.5 and §2.7.

**(c) Wording adjustment made.** None — no edit was committed. Every enumerated path is already uniquely determined by existing PRD prose, so there was nothing to widen, soften or re-scope.

## Conclusion

Step 7 applied zero implementation fixes and deleted zero tests, and the enumeration confirms why: both failures were STEP 2 test-fixture bugs against prose the PRD already pins verbatim. PRD §3.5 fixes the starting price, the ascending inclusive tier walk, the `CATEGORY`-gated exclusivity factor and the round-per-unit-then-multiply order; PRD §3.2 fixes `tier_breaks -> []` and `exclusivity_multiplier -> 1.00` as the line defaults. A fresh implementer reading PRD.md alone lands on the current `implementation/` for this subject, so no patch could add determinism without risking a new mismatch. Test_10's discriminating assertion (`cash_value_cents == 3_312_000` from Card B's 300,000 base x 1.20 seasonality x 10 units, less the 0.08 volume tier) is fully derivable from unmodified PRD prose.

## Step 9: Complete PRD — 2026-08-16T06:42:00.000Z

`workspace/PRD_COMPLETED.md` is written.

## Summary

**Source vs output** — `PRD_FINALIZED.md`: 351 lines / 72,073 bytes -> `PRD_COMPLETED.md`: 351 lines / 76,524 bytes (**+4,451 bytes**, +0 lines). All 26 edits are in-paragraph inserts/revisions across 23 lines; no new sections, no new paragraphs, section headers and both tables (43 endpoint rows, 44 error rows) byte-identical.

**Counts** — 24 ambiguity-pins, 2 mismatch-revisions.

**Changes**

- §2.1 Access Control — revise — ambiguity — an *empty* `X-User-ID`/`X-User-Role` counts as absent for `ERR_UNAUTHENTICATED` — `middleware.py:22`
- §2.3 Pagination — revise — ambiguity — non-integer `limit`/`offset` fails the same way as out-of-range — `util.py:216,224`
- §2.3 Pagination — revise — ambiguity — `created_at` ties broken by server write order; `has_more` = `offset + returned < total_count`; identifier filters are string equality, never resolved (empty page, not 404) — `db.py:180`, `response.py:437`, `routes/rate_cards.py:174`
- §2.4 Identity/Audit — insert — ambiguity — `created_at`/`updated_at`/`api_request_timestamp` come from host real time, **not** the logical clock; caller-supplied instants are echoed verbatim, never re-formatted — `db.py:138,153`, `util.py:32`, `routes/contracts.py:80`
- §2.5 Season Clock — revise — ambiguity — clock moves forward or backward freely; `data` is the single field `current_utc` echoing the supplied string; `published_at`/`delivered_at` carry that same verbatim form, not three fractional digits — `routes/properties.py:100-106`, `routes/rate_cards.py:264`, `routes/bookings.py:183`
- §2.6 Rounding — insert — ambiguity — percentages/ratios travel as bare JSON numbers (0.00 -> `0.0`) — `services/serialize.py:7-10`
- §2.7 Version Guards — insert — ambiguity — both guard fields are plain integers; missing/non-integer is rung-5 `ERR_VALIDATION_FAILED`, not a 412 — `routes/bookings.py:47`, `routes/contracts.py:220`
- §2.8 rung 5 — insert — ambiguity — absent/unparseable body treated as `{}`; a non-object JSON body is `ERR_VALIDATION_FAILED` — `util.py:109-115`
- §2.9 Cascade — revise — ambiguity — rollups bump `version` unconditionally even when the value is unchanged; the two conditional writes are sponsor rescore/churn (two separate writes -> `version` can move twice) and entitlement `makegood_credit_cents` at close — `services/cascade.py:36,60,86,103,158`, `routes/contracts.py:370,398`
- §3.4 Sponsor — insert — ambiguity — only a `PROSPECT` is promoted at countersign; `ACTIVE`/`CHURNED` are left alone — `routes/contracts.py:286`
- §3.4 Contract — insert — **mismatch** — term-vs-season checks run *after* FK resolution (`sponsor_id` then `property_id`), so an unresolvable id wins over a bad term — `routes/contracts.py:63-71`
- §3.4 Entitlement — insert — ambiguity — the linked asset is never checked against the contract's `property_id` — `routes/contracts.py:150`
- §3.5 Submit — revise — ambiguity — any `SponsorshipSeller` may submit (no drafter comparison) — `routes/contracts.py:180-194`
- §3.5 Submit — insert — ambiguity — the `DRAFT` state check precedes all three declared gates — `routes/contracts.py:183`
- §3.5 Return — insert — ambiguity — `reason` (return, terminate, cancel) is validated as a string but persisted nowhere — `routes/contracts.py:204,318`, `routes/bookings.py:147`
- §3.7 StaffAssignment — insert — ambiguity — the booking's `status` is not tested at rostering — `routes/staff.py:359-375`
- §3.7 StaffAssignment — insert — ambiguity — shift minutes = elapsed seconds / 60, truncated — `util.py:89-91`
- §3.7 Check-in — revise — ambiguity — assignment must still be `ASSIGNED` (else `ERR_INVALID_STATE`); no contract/property state consulted — `routes/staff.py:439-445`
- §3.8 Proof capture — revise — **mismatch** — the booking's `status` is never tested; `CANCELLED`/`PREEMPTED` bookings accept evidence — `routes/proofs.py:228-251`
- §3.8 Proof capture — insert — ambiguity — capture always rewrites the booking row (`version` +1) while money/`delivered_units` stay put — `services/cascade.py:31-36`
- §3.8 Adjudication — insert — ambiguity — a `reject_reason` sent with a `VERIFIED` decision is ignored (stays null); verification runs no entitlement/contract/property rollup, only proof + booking rows advance — `routes/proofs.py:281-299`
- §3.9 Close — revise — ambiguity — `delivered_media_value_cents` joins the list of fields *not* recomputed at close — `routes/contracts.py:356-384`
- §3.9 Makegood — insert — ambiguity — `WAIVED` entitlements are absent from the ordering and keep their existing credit — `services/calc.py:232,237`
- §3.9 Close — insert — ambiguity — close (and countersign, and terminate) is a single rewrite of the contract row -> `version` +1 exactly — `routes/contracts.py:284,323,384`
- §3.9 ROI report — insert — ambiguity — a `basis` outside `VERIFIED`/`GROSS` is `ERR_VALIDATION_FAILED` — `routes/contracts.py:456`
- §3.9 ROI report — insert — ambiguity — the proof sweep is not confined to contributing bookings: proofs on a still-`SCHEDULED` booking count toward `impressions_total` under either basis — `routes/contracts.py:478-484`

**Verified as already uniquely pinned (no change):** all 43 endpoint role lists match `middleware.endpoint(...)` exactly; the full 17-rung rejection ladder; all 8 calculations including the three dual-variant pairs (conservative/audited in-kind, survey/no-survey renewal weighting, VERIFIED/GROSS basis); both version guards and their check positions; the 44 error->status mappings in `errors.ERROR_STATUS`; half-open booking windows vs. closed shift intervals; the changeover-buffer and 45-minute-rest boundary semantics (`gap < limit` fails, equality passes); and the write-once field sets for rate-card lines and surveys.
