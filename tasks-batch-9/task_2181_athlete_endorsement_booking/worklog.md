# Worklog — task_2181_athlete_endorsement_booking

## Step 1: Create task directory — 2026-08-30T04:29:06.000Z

Created `tasks/task_2181_athlete_endorsement_booking/` and `tasks/task_2181_athlete_endorsement_booking/workspace/`.

## Step 3: Copy shared files — 2026-08-30T04:29:27.000Z

Copied `INSTRUCTION.md` from project root to `workspace/INSTRUCTION.md`. (Run ahead of Step 2's completion; no dependency on the scaffold.)

## Step 2: Generate scaffold — 2026-08-30T05:10:00.000Z

All three scaffold artifacts are written, valid YAML, and pass the skill's linter clean.

## Summary

**Output** — `/home/ubuntu/github/CodingPRD/tasks/task_2181_athlete_endorsement_booking/`
- `SCAFFOLD.yaml` (2,281 lines) — §1.0–§1.7 + §1.2.1; no design keys inside
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1,571 lines) — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (3,370 lines) — single key `scaffold_corner_design`

**Complexity profile**: primary `multi_party_negotiation` + secondary `temporal_windowing`; layers `optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers`; topology **flat**, state-machine shape **cyclic**, role model **segregation_of_duties**, consistency **immediate**; difficulty band expert-plus. `api_prefix: "/"`.

**§1.1–§1.7 counts**: 13 entities (Athlete, Brand, Opportunity, TermSheet, Engagement, ExclusivityGrant, AppearanceBooking, ProductionSlot, Deliverable, DisclosureRecord, PayoutStatement, RenewalOption, LedgerEntry[append-only]) · 10 state machines (Engagement carries two parallel dimensions: `contract_status` × `settlement_status`) · 2 OCC concurrency rules (both on `Engagement.version`, payout-create-supersede and booking-create) · 6 calculations · 43 validations · 50 endpoints (incl. `POST /_clock/set_current_utc`, default clock **2026-08-01T00:00:00Z**) · 42 errors · 5 roles (TalentAgent, BrandRep[entity_backed:Brand], Athlete[entity_backed:Athlete], ComplianceOfficer, FinanceManager).

**§1.8 — 19 instances across all 9 rule ids** (≥2 each): `dual_variant_calc` 2, `combinatorial_formula` 3 (modes a/b/c), `non_linear_state_machine` 2, `transitive_cascade` 2, `priority_pair_validation_conflict` 2, `boundary_precision_check` 2, `cross_entity_state_dependency` 2, `resource_temporal_overlap` 2, `compensating_invariant` 2. Key pinned literals (all computed in code): provisional 2 621 400 vs binding 3 001 900; payout gross 3 001 901 / commission 450 286 / net 2 551 615 (vs 3 001 900 / 450 285 under sum-then-round); renewal TIER_2 bonus 203 000, total 3 103 000, fee 1 728 000; fit score exactly 60 vs 59; exposure 28 vs 52.

**§1.9 — 72 instances (59 active + 13 `excluded_because` stubs)** across all nine guide sections: entities 11, state_machines 12, calculations 8, validations 14, endpoints 4, errors 10, rbac 6, cross_cutting_complexity_layers 6, consistency_model 1.

**Verification**: `scaffold_lint.py` verdict —
```
  §1.5 endpoints declared:    50
  §1.1 entities declared:     13
  §1.8 instances scanned:     19
  §1.9 instances scanned:     59
  Calls scanned (§1.8+§1.9):  876
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Plus custom checks: 0 unbound `${var}` across 876 calls, all instance names unique across both files, all `grounds` refs resolve into §1.1–§1.7, every one of the 42 error ids is referenced by a design instance, all 13 stub `difficulty_instance` citations resolve, and no forbidden concurrency vocabulary anywhere.

## Step 4: Generate PRD — 2026-08-30T05:22:00.000Z

All three hard contracts pass and the coverage audit is clean.

**PRD generated:** `workspace/PRD.md` — **405 lines**, built incrementally in 6 append passes (no single-Write truncation risk).

**Section list (25 headings):** §1 Introduction; §2 Global Specifications (2.1 Desk Roles and Caller Identity · 2.2 API Response Structure · 2.3 Pagination · 2.4 Resource Identity, Timestamps and the Logical Clock · 2.5 Version Stamping and Optimistic Concurrency on Engagements · 2.6 Money, Rounding and the Append-Only Ledger · 2.7 Three Kinds of Occupied Capacity · 2.8 Order of Evaluation · 2.9 Cascades and Derived Counters · 2.10 Sanctions and Roster Status); §3 Business Logic & Workflows (3.1 Building the Roster and Filing an Opportunity · 3.2 Brand-Fit Screening · 3.3 Papering the Deal: Rounds, Counters and Revisions · 3.4 Acceptance: Minting the Engagement and Locking the Category · 3.5 Countersignature and the Binding Fee · 3.6 Appearance Logistics and Travel Accrual · 3.7 Production Slots, Deliverables and the Approval Cascade · 3.8 Disclosure Compliance for Paid Promotion · 3.9 Termination and the Four-Hop Unwind · 3.10 Settlement, Renewal and Exposure Reporting); §4 Endpoint Definitions; §5 Error Code Catalogue.

**Coverage audit (verified programmatically against SCAFFOLD.yaml):** entities 13/13 · state machines 10/10 (incl. both Engagement dimensions: `contract_status` 4 + `settlement_status` 4) · state transitions 42/42 · calculations 6/6 (brand_fit_score, appearance_fee_engine w/ PROVISIONAL+BINDING, payout_distribution, athlete_exposure_risk_score w/ both variants, performance_bonus_and_renewal, booking_travel_days) · validations 43/43 (full priority ladder 10→86 stated as an ordered chain in §2.8) · endpoints 50/50 · errors 42/42 (all also referenced in §2/§3 prose) · roles 5/5 (2 entity-backed, 3 opaque) · clock endpoint + default `2026-08-01T00:00:00Z` stated. 0 missing in every category.

**Contract 1 — Field-Name Coverage: PASS** — entity fields 111/111; request_body 67/67; query_params 16/16.

**Contract 2 — Rule Coverage: PASS** — validations 43/43; OCC concurrency rules 2/2 (`POST /appearance-bookings`, `POST /payout-statements`, both with `expected_engagement_version` + `ERR_STALE_ENGAGEMENT_VERSION` + 412); transitions 42/42 with preconditions + side effects; calculations 6/6 with rounding positions pinned; validation→error_id mapping 43/43; endpoint side_effects/scopes 50/50; field structured content 111/111; sibling-branch symmetry 8/8 groups with equal density, 0 asymmetric.

**Contract 3 — §3 Path Purity: PASS** — 753 backtick tokens scanned in §3 (289 distinct); 0 tokens starting with `/`, 0 bare HTTP-method tokens, 0 method+path tokens.

Additional verifications: §2.2 block byte-identical to the canonical response-structure block; zero fuzzy/approximating words; zero pseudocode operators in prose; zero scaffold-internal references leaked into §4 descriptions; document ends at the §5 table. The two withheld design indices were never opened.

## Step 6: Generate implementation — 2026-08-30T05:45:00.000Z

Implementation complete and verified.

**Location:** `workspace/implementation/`

### Modules written (2,453 lines Python + `start.sh` + `requirements.txt`)

| File | Lines | Contents |
|---|---|---|
| `app.py` | 71 | Flask entry point, blueprint registration, envelope-shaped error handlers, global request lock, `0.0.0.0:$PORT` (default 10000) |
| `errors.py` | 58 | All 42 error IDs → HTTP status map, `ApiError` |
| `store.py` | 128 | In-memory dict tables (13), logical clock (epoch `2026-08-01T00:00:00Z`), UUID/`req_` id minting, 3-fractional-digit ISO stamps, `touch()` (version+updated_at), `_seq` tiebreak ordering |
| `envelope.py` | 91 | `meta`/`response_type`/`data` success + error envelopes; `limit`/`offset`/`total_count`/`has_more` pagination (default 10, min 1, max 100) |
| `auth.py` | 48 | `X-User-ID`/`X-User-Role`, 5 roles, `ERR_UNAUTHENTICATED`/`ERR_FORBIDDEN_ROLE` |
| `validation.py` | 143 | Schema readers (str/enum/int/number/bool/date/datetime/id) all raising `ERR_INVALID_REQUEST` |
| `calc.py` | 221 | `Decimal` ROUND_HALF_UP throughout: brand-fit score, appearance-fee engine (PROVISIONAL/BINDING), travel-days ceiling, payout waterfall, bonus-and-renewal, month arithmetic |
| `domain.py` | 335 | Derived counters, append-only ledger + `accrued_fee_cents`, exposure risk (both variants), the three occupancy conventions (closed-inflated calendar / half-open slot sweep with aggregate ceiling / inclusive day-range register), void + termination cascades, path/body 404 resolution |
| `routes/core.py` | 136 | clock, athletes, brands |
| `routes/negotiation.py` | 385 | opportunities, screening, term-sheet draft/submit/counter/revise/withdraw/accept |
| `routes/engagements.py` | 172 | reads, countersign, terminate unwind, ledger/grants/statements/options lists |
| `routes/bookings.py` | 198 | appearance bookings + production slots |
| `routes/deliverables.py` | 181 | scheduling, submit, review + approval cascade |
| `routes/disclosures.py` | 119 | file, rule (segregation of duties + tag set), remediate |
| `routes/settlement.py` | 167 | payout build/supersede/disburse, renewal open/decide |

### Coverage
- **50/50 endpoints** routed — verified programmatically against the PRD §4 table (0 missing, 0 extra).
- **42 errors**, 13 entities, 10 state machines (incl. the two independent Engagement dimensions) implemented.
- **§2.8 ladder honoured literally** (PRD over scaffold where they differ): auth → role → path FKs left-to-right → schema → body FKs → ownership → OCC → the 26-step domain order. Notably athlete-bookability precedes term-sheet from-state, and exclusivity conflict precedes fee cap.
- **Storage is in-memory only**, empty on every boot — no seeding, no files, no SQLite.

### Verification
Four scripted end-to-end passes against a live server confirmed, among others: brand-fit 87/26, provisional 930450, binding 965450 with travel, cap clamping at 975000, payout lines 139286/557143/278571 with residue-free gross and per-line commission 195000, no-show penalty −96545, travel_days=1 at an exactly-24.0h padded span, touching-endpoint booking collision vs. 1-second gap passing, back-to-back shoots not contending vs. overlap rejected, grant range `2026-09-01 → 2027-02-28` for a 6-month lock, boundary-day exclusivity conflict vs. clean adjacency, lazy offer expiry and lazy renewal lapse both mutating then refusing, payout supersede voiding the standing DRAFT, and the full four-front termination unwind (grants RELEASED, bookings AUTO_TERMINATION + REVERSAL, deliverables VOIDED + slot `reserved_count` freed, settlement opened).

**Boot check:** `bash start.sh` on a free port responded within a second (dependency install guarded by a cheap `import flask`), served the clock endpoint, returned a correct error envelope, and reported an empty store; process then killed cleanly. `__pycache__` removed.

## Step 5: Generate unit tests — 2026-08-30T06:12:00.000Z

Test infrastructure and suite generated for `task_2181_athlete_endorsement_booking`.

## Files written

**`test_helpers/` (1,997 lines)**
| file | lines |
|---|---|
| `__init__.py` | 41 |
| `types.py` | 418 |
| `api_client.py` | 213 (one method per PRD endpoint, 51 methods) |
| `api_errors.py` | 97 (42 error ids + status map, registered with framework) |
| `assertions.py` | 237 (per-entity assertions, ledger/accrual invariants, instant comparison) |
| `factories.py` | 239 |
| `constants.py` | 77 |
| `test_users.py` | 53 (shared constants + per-instance builders for the two `entity_backed` roles) |
| `fixtures.py` | 622 (Tier 0 primitives → `build_deal` chain → threshold/accumulation fixtures) |

**`test_suite/` (3,615 lines, 97 tests)** — `conftest.py` (52) plus `test_01_roster_and_intake` (12 tests), `test_02_screening_and_negotiation` (14), `test_03_acceptance_and_countersignature` (12), `test_04_appearance_logistics` (13), `test_05_deliverables_and_production_slots` (11), `test_06_disclosure_compliance` (7), `test_07_settlement_and_payouts` (12), `test_08_renewal_and_exposure` (8), `test_09_termination_and_the_unwind` (8).

## Coverage

- **Queue A (Difficulty): 19/19 instances translated, 0 skipped** — 2 tests each = 38 tests.
- **Queue B (Corner): 59/59 active instances translated, 0 skipped** — 1 test each = 59 tests. All 13 `excluded_because:` stubs verified to resolve to real difficulty instances and **not** translated.
- **Total 97 tests, 78 distinct `Design:` tags**, every tag resolving to a real instance; no untagged or dual-tagged test.

## Verification performed

- `python3 -m py_compile` / `compileall` on every file; `pytest --collect-only` collects 97 tests cleanly; `pyflakes` reports no undefined names and no unused imports.
- Automated citation audit: every test docstring carries ≥1 PRD quote whose whitespace-normalised text is a literal substring of `PRD.md` (0 failures), and exactly one trailing `Design:` line.
- No `skip` / `skipif` / `xfail` anywhere; no "scaffold"/section references leak into generated code.

## One deliberate deviation from a design-index literal

`Difficulty/non_linear_state_machine/term_sheet_counter_revise_cycle_increments_round` asserts `provisional_fee_cents == 2451300` after a revise that sets `morals_clause_tier: TIER_A`. That figure corresponds to the **TIER_B** morals multiplier (1.35 × 1.05 × 1.20 = 1.701) and is inconsistent with the recipe's own trigger payload. PRD §3.3 ("recomputes `provisional_fee_cents` by exactly the same rules as submission") uniquely derives `1300000 × 1.35 × 1.15 × 1.20 = 2421900` rights + `240000` uplift = **2661900**, which is what the test asserts. This is a scaffold-design arithmetic bug, not a test relaxation.

## Step 7: Run tests and iterate — 2026-08-30T06:25:00.000Z

All checks pass. The implementation source is untouched (mtimes all from generation at 05:25–05:33; my only two edits are test-side at 05:53), storage is in-memory only, no skip/xfail was introduced, and all 97 tests remain.

## Summary

**Iterations run: 2.** Sweep 1 → 95/97 in all 8 rounds (2 deterministic failures, no flakiness). Sweep 2 → **97/97 in all 8 rounds, union of failures across rounds: NONE.**

**Tests deleted: none.** Both failures survived STEP 1 — each asserted a rule quoted verbatim from the PRD, and each was uniquely derivable. Neither hit a silence or collapse pattern, so under the protocol both went to STEP 2, where both turned out to be test-side defects.

**Fixes applied to `test_helpers/` (1):**
- `test_helpers/fixtures.py` — `setup_deliverable_awaiting_disclosure` funneled all `**kwargs` into `build_deal`, so a caller passing `platform="TIKTOK"` crashed with `TypeError: build_deal() got an unexpected keyword argument 'platform'`. `platform` is a DisclosureRecord field, not a deal-building one. Added it as an explicit parameter forwarded to `file_disclosure`. `TIKTOK` is a PRD-declared member of the platform enum, so the test's intent was legitimate and the helper was simply unable to express it.

**Fixes applied to `test_suite/` (1):**
- `test_suite/test_05_deliverables_and_production_slots.py` — `test_submitting_an_approved_deliverable_is_refused` expected `ERR_DELIVERABLE_INVALID_STATE` but got `ERR_ENGAGEMENT_NOT_ACTIVE`. **Ladder masking, not an implementation bug.** The fixture built a one-deliverable engagement, so approving that single line drove the engagement `ACTIVE → COMPLETED` — and PRD §2.8 places engagement contract-status fitness *above* deliverable from-state in the evaluation ladder. The server was correctly reporting the first rung the request violated. Fixed the setup (two planned posts, `proposed_fee_cents` 200,000) so the engagement stays `ACTIVE` after one approval and the assertion under test is actually reached.

**Fixes applied to `implementation/`: none.** Neither failure traced to the server; both were setup/helper defects, so no PRD-required check was weakened to accommodate a fixture.

**On the caveat flagged mid-loop:** the two-post fixture leaves the brand-fit score on the exact 60 pass/fail boundary, so a miscalculation would have surfaced as a setup-time `ERR_OPPORTUNITY_NOT_SCREENED` rather than the assertion under test — a pass for the wrong reason is indistinguishable from a real one in the log alone. Verified two ways: the test is recorded `PASSED` in all 8 rounds (a screening rejection would have raised inside `build_deal` before the assertion ran), and the implementation's own `calc.brand_fit` was run against both configurations — the new two-post fixture scores **exactly 60 and screens in, identical to the original one-post fixture**. The change is score-neutral; it only raises `required_deliverable_count` from 1 to 2.

**Deliverables left in place:** `workspace/implementation/results.{1..8}.json`, all eight reporting `total=97 passed=97 failed=0 errors=0 skipped=0` (~123s per round).

## Step 8: Finalize PRD — 2026-08-30T06:35:00.000Z

Done. `PRD_FINALIZED.md` is created as a byte-identical copy of `PRD.md` — **no edits were warranted.**

## Line counts
- `PRD.md`: 405 lines
- `PRD_FINALIZED.md`: 405 lines
- Delta: **0 lines, 0.0%** (files are byte-identical)

## Changes
None. Both `<step_7_diff>` items were test-side defects against behavior the PRD already uniquely determines.

## Per-item verification log

**Item 1 — `test_helpers/fixtures.py::setup_deliverable_awaiting_disclosure` (`platform` kwarg crash)**
- (a) Subject: the `DisclosureRecord.platform` field and its accepted enum members.
- (b) Impl paths enumerated: `routes/disclosures.py:35` (`create_disclosure` → `V.enum_field(payload, "platform", calc.PLATFORMS)`), `:53` (persisted onto the record), `calc.py:14` (`PLATFORMS = ("INSTAGRAM", "X", "TIKTOK", "YOUTUBE", "BROADCAST")`), `validation.py:79-85` (`enum_field` is `required=True` by default, rejects non-members with `ERR_INVALID_REQUEST`). Grepped `platform` across `calc.py`, `domain.py`, `validation.py`, `routes/*.py` — `create_disclosure` is the sole write site; `rule`/`remediate` never touch it, so there is no second path with a different member set.
- (c) No wording adjustment needed. PRD §3.8 (line 257) already names the field, marks it required by construction ("naming the `deliverable_id` it covers, the `platform` on which the asset was published"), and enumerates exactly the five members the impl accepts, `TIKTOK` included. This was a pure helper defect — the PRD was never silent.

**Item 2 — `test_suite/test_05` `test_submitting_an_approved_deliverable_is_refused` (ladder masking)**
- (a) Subject: the relative rung order of engagement contract-status fitness vs. deliverable from-state, and the engagement `ACTIVE → COMPLETED` auto-transition on final deliverable approval.
- (b) Impl paths enumerated: `routes/deliverables.py:116-119` (`submit_deliverable` — engagement `ACTIVE` check precedes the deliverable from-state check), `:139-142` (`review_deliverable` — the parallel endpoint, same ordering), `:113-114` and `:136-137` (ownership precedes both, matching the ladder), `:38-39` (`create_deliverable`'s wider `PENDING_COUNTERSIGN`/`ACTIVE` fitness test), `:160-168` (the approval cascade: `refresh_approved_deliverable_count` → `>= required_deliverable_count` → `contract_status = "COMPLETED"` → `open_settlement` → `sync_athlete_after_contract_change`), `domain.py:127-131`, `domain.py:323-327` (`open_settlement`, `UNBILLED → BILLABLE` only), `domain.py:329-335` (exposure resync on contract-dimension change). Also checked `calc.py:91-121` (`brand_fit`) since the fixture raised `proposed_fee_cents` to keep the score above the 60 gate with two planned posts — the formula matches PRD §3.2 exactly, so the fixture's new numbers are PRD-derivable, not impl-pinned.
- (c) No wording adjustment needed. PRD §2.8 (line 133) already orders `ERR_ENGAGEMENT_NOT_ACTIVE` (engagement contract-status fitness) strictly above `ERR_DELIVERABLE_INVALID_STATE` (deliverable from-state) in the ladder, exactly as the server enforces; PRD §3.7 (line 253) already states the four-hop cascade including `ACTIVE → COMPLETED` when `approved_deliverable_count` reaches `required_deliverable_count` and the consequent `UNBILLED → BILLABLE`; PRD §3.4 (line 203) already pins `required_deliverable_count` as the sum of the three planned counts. The server was reporting the first violated rung correctly — the fixture, not the PRD, was wrong.

**Fixes applied to `implementation/`: none**, so no rung was weakened and there is no impl-side choice left unpinned by the existing prose. Adding text here would have risked a new mismatch (e.g. any sentence narrowing the fitness rung to "ACTIVE only" would mis-describe `create_deliverable`'s `PENDING_COUNTERSIGN`-or-`ACTIVE` acceptance at `routes/deliverables.py:38`), which is precisely what the NO-NEW-MISMATCH rule forbids.

## Step 9: Complete PRD — 2026-08-30T06:45:00.000Z

`workspace/PRD_COMPLETED.md` is written.

## Summary

**File**: `workspace/PRD_COMPLETED.md`
- Source `PRD_FINALIZED.md`: 405 lines / 72,260 chars
- Result `PRD_COMPLETED.md`: 405 lines / 77,716 chars (**+5,456 chars**, +0 lines — every change is an in-paragraph insert/revise; no new sections, no new paragraphs)
- 30 edits: **28 ambiguity-pins**, **2 mismatch-revisions**

### Changes

- §2.2 envelope — insert — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case alphanumerics — `store.py:66-68`
- §2.2 envelope — insert — **mismatch** — `api_request_timestamp` is real wall-clock, explicitly *not* pinned by the logical clock (§2.4 implied all stamps are logical) — `envelope.py:17-27`
- §2.3 pagination — insert — ambiguity — non-integer `limit`/`offset` and negative `offset` → `ERR_INVALID_REQUEST`; empty-string values fall back to defaults — `envelope.py:56-70`
- §2.3 pagination — insert — ambiguity — `created_at` ties (the normal case under a frozen clock) break by insertion order; list filters are exact string matches that never 400 on an out-of-set value — `store.py:126-128`, `routes/negotiation.py:95-98`
- §2.4 clock — revise — ambiguity — `to_iso8601` required; answers 200 with `data` carrying only `current_utc`, echoed in three-fractional-digit form — `routes/core.py:16-22`
- §2.5 concurrency — insert — ambiguity — full enumeration of which operations do and do not increment the engagement `version` (9 that do, 9 that don't) — `routes/bookings.py:67,114,142,166`, `routes/engagements.py:65,122`, `routes/deliverables.py:166`, `routes/settlement.py:188,210,282`
- §3.1 roster — insert — ambiguity — athlete-status `reason` is validated but not persisted — `routes/core.py:65-66`
- §3.1 brands — revise — ambiguity — `compliance_rating` must be a whole number — `routes/core.py:106`
- §3.1 opportunity — insert — ambiguity — body FK order is `athlete_id` then `brand_id`; ownership runs after both resolve — `routes/negotiation.py:55-59`
- §3.2 screening — insert — ambiguity — screening a non-`INTAKE` opportunity → `ERR_OPPORTUNITY_NOT_SCREENED` — `routes/negotiation.py:106-107`
- §3.3 counter — revise — ambiguity — `counter_fee_cents` ≥ 1, `counter_exclusivity_months` 0–36, `note` not persisted — `routes/negotiation.py:203-207`
- §3.3 revise — insert — ambiguity — all six revision fields required; `territory`/`exclusivity_category` not revisable — `routes/negotiation.py:234-260`
- §3.3 withdraw — insert — ambiguity — `reason` not persisted — `routes/negotiation.py:274`
- §3.4 acceptance — insert — **mismatch** — the five guards are tested in §2.8 ladder order, not narration order; exclusivity precedes the fee cap — `routes/negotiation.py:322-327`
- §3.4 grant range — insert — ambiguity — month arithmetic clamps to the last valid day of the target month; a zero-month lock mints an empty range that neither conflicts nor blocks — `calc.py:73-87`, `domain.py:228,238`
- §3.4 acceptance — insert — ambiguity — accept answers **201** with the minted engagement, not the term sheet — `routes/negotiation.py:385`
- §3.5 countersign — revise — ambiguity — `signed_by_reference` required but not persisted — `routes/engagements.py:40`
- §3.6 booking create — revise — ambiguity — `city` is a required string — `routes/bookings.py:24`
- §3.6 confirm — revise — ambiguity — `travel_cost_cents` required, non-negative — `routes/bookings.py:94`
- §3.6 no-show — insert — ambiguity — a null `binding_fee_cents` yields a zero penalty and a zero-amount `PENALTY` entry is still appended — `routes/bookings.py:137-141`
- §3.6 cancel — insert — ambiguity — `reason_code` required; close and cancel test no engagement `contract_status` — `routes/bookings.py:118-159`
- §3.7 approval cascade — insert — ambiguity — completion test is *at least* (`>=`), so a required total of 0 completes on the first approval — `routes/deliverables.py:162`
- §3.8 filing — insert — ambiguity — filing tests no engagement status — `routes/disclosures.py:30-49`
- §3.8 compliant ruling — insert — ambiguity — `finding_note` stored on both branches (null when omitted); a `COMPLIANT` ruling also recomputes `exposure_risk_snapshot_score` — `routes/disclosures.py:89,92`
- §3.8 remediation — insert — ambiguity — remediation leaves the earlier `finding_note` standing — `routes/disclosures.py:111-115`
- §3.10 statement — insert — ambiguity — `athlete_net_cents` has no floor and may go negative — `calc.py:179`
- §3.10 renewal — insert — ambiguity — `required_deliverable_count` of 0 yields `approval_rate` 0.0000 → `NONE`; all six figures are frozen onto the option row — `calc.py:187-192`, `routes/settlement.py:238-250`
- §3.10 lapse — insert — ambiguity — a lapsed option leaves `decided_at` null — `routes/settlement.py:270-275`
- §3.10 exposure — insert — ambiguity — empty `variant` defaults to `ROSTER_SNAPSHOT`; any other value → `ERR_INVALID_REQUEST` — `routes/core.py:75-79`
- §4 endpoint table intro — insert — ambiguity — accept is a 201-creating operation; the clock endpoint is 200 — `routes/negotiation.py:385`, `routes/core.py:22`

### Notes
- Two items deliberately left alone as framework-level rather than PRD behavior: Flask's 404/405 fallbacks in `app.py:52-61` (mapped to `ERR_INVALID_REQUEST`) — no PRD passage naturally hosts them, and adding one would mean a new paragraph.
- The clean Step 7/8 record was indeed not evidence of completeness: none of the 30 gaps above were covered by the passing suite, and two (the wall-clock `api_request_timestamp`, and the acceptance guard-ordering narration) were outright mismatches against the shipped code.
