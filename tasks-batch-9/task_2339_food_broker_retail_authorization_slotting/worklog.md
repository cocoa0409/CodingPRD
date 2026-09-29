# Worklog — task_2339_food_broker_retail_authorization_slotting

## Step 1: Create task directory — 2026-09-01T19:45:22.225Z

Created `tasks/task_2339_food_broker_retail_authorization_slotting/` and `tasks/task_2339_food_broker_retail_authorization_slotting/workspace/`.

## Step 2: Generate scaffold — 2026-09-01T21:32:33.611Z

All three scaffold artifacts are complete and lint-clean.

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2339_food_broker_retail_authorization_slotting/`):
- `SCAFFOLD.yaml` (2,313 lines) — §1.0–§1.7 only; verified no `scaffold_difficulty_design` / `scaffold_corner_design` keys.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2,208 lines) — single top-level key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` (4,983 lines) — single top-level key `scaffold_corner_design`.

SCAFFOLD.yaml contents
- `domain_name: food-broker-authorization-slotting`, `api_prefix: ""`, envelope `{ success, data, error_id, message }`.
- 12 entities: Retailer, Principal, CommissionAgreement, Item, CategoryReview, Presentation, SlottingDeal, Authorization, DistributionSnapshot, Promotion, Deduction, PrincipalConflictRule (entity_topology `graph`, state_machine_shape `cyclic`).
- 12 state machines, 3 §1.2.1 concurrency rules (`deal-accept-stale-principal` / `snapshot-post-stale-authorization` / review-decide OCC), 7 calculations, 36 validations (12-rung priority ladder), 64 endpoints, 82 errors, 5 peer roles (BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer `entity_backed:Retailer`, PrincipalPortalUser `entity_backed:Principal`).
- Complexity layers: dual_variant_calculation, cascading_side_effects, optimistic_concurrency, rate_threshold_triggers; consistency model `immediate`.

Difficulty design (§1.8): 9 rule blocks × 2 = 18 instances (dual-variant divergence, ordering-sensitive cascades, priority-pair traps, boundary clusters, money/store-count conservation).

Corner design (§1.9): 46 instances across all 9 guide sections — entities 9, state_machines 12, calculations 8, validations 10, endpoints 6, errors 2, rbac 3, cross_cutting_complexity_layers 6, consistency_model 1. 11 of those are `excluded_because` stubs pointing at the §1.8 instance that already covers the corner; 35 carry full `test_recipe`s. All 75 instance names are unique across both design files.

Verification
- `scaffold_lint.py`: "VERDICT: clean lint" — 1,313 §1.8+§1.9 calls checked against §1.5 endpoints/roles/inputs, plus FK reverse-reachability.
- Error catalog coverage: 82/82 triggered, 0 untriggered (the final batch consumed ERR_STALE_REVIEW_VERSION, ERR_STALE_AUTHORIZATION_VERSION, ERR_STALE_PRINCIPAL_VERSION).
- The hard constraint held throughout: nothing under any sibling `tasks/task_*/` was listed, globbed, grepped, or read.

Notable hardening in the closing batch: the three OCC instances assert that the 412 outranks lower-priority failures in the same request (stale authorization version beats `ERR_PERIOD_ALREADY_POSTED` and the sequence/aggregate bounds; stale principal version beats `ERR_SLOTTING_BUDGET_EXCEEDED`), that rejected writes never bump `version`, and that reversals bump the version without carrying an expected-version field — forcing a genuine re-read loop.

## Step 3: Copy shared files — 2026-09-01T21:32:33.611Z

Copied `INSTRUCTION.md` to `tasks/task_2339_food_broker_retail_authorization_slotting/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T21:52:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2339_food_broker_retail_authorization_slotting/workspace/PRD.md` (486 lines, 94 KB). Only `SCAFFOLD.yaml`, the skill spec and its §2.2 fragment were read; neither design index nor any sibling task directory was opened.

**Structure**
- §1 Introduction — 3 paragraphs from the scenario (broker↔principal↔chain framing, conserved-money design, logical clock + version pinning).
- §2 Global Specifications — 2.1 RBAC (all five roles, `X-User-ID`/`X-User-Role`, entity-backed vs opaque identity, catalog-decision scope exemption), 2.2 Response Structure (pasted verbatim), 2.3 Pagination/Ordering/List Filters (all 31 query params), 2.4 Resource Identity & Audit Fields (incl. the `DistributionSnapshot` `common_fields: false` exception), 2.5 Logical Clock/Dates/Half-Open Windows (`2026-08-01T00:00:00Z` startup, no wall-clock fallback), 2.6 Money/Basis Points/Rounding (floor vs round-half-up, 2-decimal `cost_per_forecast_unit_cents`), 2.7 OCC (all three pins with endpoint + field + error), 2.8 Validation Order (full 12-band precedence ladder), 2.9 Cascade Discipline (4 conserved invariants + aggregate re-derivation + version bumps), 2.10 Reference Resolution & Uniqueness (12 404 codes, 6 uniqueness rules).
- §3 Business Logic — 9 subsections: trading partners & conflict edges; commission agreements/exclusivity/statements; item setup, UPC mod-10 & catalog cycle; review calendar & presentation prep; slotting negotiation & the 7-step quote ladder; award decision fork + acceptance cascade (3 hops); distribution/voids/amortization (6 ordered steps, both dual variants); promotions/samples/demo capacity; deductions, post-audit recovery by reason code & credit posture.
- §4 — 201-vs-200 intro paragraph plus a 4-column table with all 64 endpoints.
- §5 — 2-column table with all 82 error codes. Document ends at §5; no audit footer inside the file.

**Coverage audits (scripted against SCAFFOLD.yaml)**

```
Field coverage check:
- entities[].fields: 128 required, 128 present, 0 missing
- endpoints[].request_body: 81 required, 81 present, 0 missing
- endpoints[].query_params: 31 required, 31 present, 0 missing
- computed response-shape fields: 15 required, 15 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 36 checked, 36 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 57 checked, 57 fully expressed, 0 missing
- calculations[]: 7 checked, 7 fully expressed, 0 missing
- validations[] conditions: 82 error IDs checked, 82 matchable to prose outside the §5 table, 0 missing
- endpoints[].side_effects / applies_to: 38 checked, 38 expressed, 0 missing
- entities[].fields[] structured content: 128 checked, 128 reconstructible from prose, 0 missing
- sibling-branch symmetry: 11 groups checked, 11 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 980
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verifications: §2.2 block is byte-identical to `section-2.2-response-structure.md`; all 64 endpoint rows match scaffold method/path and role lists exactly (0 mismatches); all 82 error rows match scaffold HTTP status (0 mismatches, 0 extras); zero pseudocode operators (`==`, `>=`, `+=`, `floor(`, `min(`, `round_half_up(`) and zero fuzzy quantifiers remain in the prose.

## Step 5: Generate unit tests — 2026-09-02T00:12:46.934Z

The suite is complete.

## Files written

**`test_helpers/`** (8 files, Stage 1): `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py` — generic HTTP client per declared endpoint, payload factories with `**overrides`, error-id/enum constants, role header builders, and composite fixtures that rebuild every precondition through public endpoints only (all function-scoped, since the harness resets the DB per test).

**`test_suite/`**: `conftest.py` (only `api` + the four role-header fixtures; never touches the clock) plus **62 test files** `test_01_*.py` … `test_62_*.py`.

Final two files added this session:
- `test_61_stale_principal_version_outranks_the_budget_check.py` (9 tests) — 412 `ERR_STALE_PRINCIPAL_VERSION` (band 6) beating `ERR_SLOTTING_BUDGET_EXCEEDED` (band 12) on the same accept, and the forced double retry because curing the budget bumps the principal again.
- `test_62_the_accept_response_already_shows_the_whole_cascade.py` (7 tests) — immediate consistency: the accept body already reports `AMORTIZING` with the frozen fee, and the next reads show both authorizations moved, shares summing exactly, and the principal's aggregates re-derived.

## Test counts

- **362 tests total**, all collecting cleanly (`pytest test_suite --collect-only -q` → 362).
- **Queue A (Difficulty): 96 tests** across **18/18** non-stub instances (every instance ≥ 2 tests).
- **Queue B (Corner): 266 tests** across **46/46** non-stub instances (all 8 sections: entities 8, state_machines 9, calculations 6, validations 8, endpoints 6, errors 2, rbac 3, cross_cutting 3, consistency_model 1).

## Audits (all green)

- Every test docstring ends with exactly one `Design:` line; **0** untagged, dual-tagged, or unknown tags; **0** missing instances in either index.
- Verbatim-citation auditor: **475 PRD quotes, 0 problems** (each appears exactly once in the whitespace-normalized `workspace/PRD.md`).
- `pyflakes` clean over `test_suite/` and `test_helpers/`.

## Instances skipped

**None** — every non-stub instance in both indices produced at least one test. Stub instances carrying `excluded_because:` were not translated, by design.

Three *assertion-level* PRD-first deviations (the instance was still translated, the ungrounded claim dropped):
1. `test_48` — the design's `counterfactual_void_rate_bps == 10000` on an empty ledger; PRD does not uniquely derive that value with no postings.
2. `test_51` — "no DELETE endpoint exists" (no verbatim PRD coverage; the endpoint table's absence is not a stated rule).
3. `test_57` — the claim that a `PrincipalPortalUser`'s *collection* reads are silently identity-filtered; PRD scopes only single-resource reads via `ERR_PRINCIPAL_SCOPE_FORBIDDEN`.

One judgement call kept: item creation is genuinely ungated on principal status (`test_55`), since PRD enumerates item-creation's checks exhaustively and locates the status gate on catalog submission.

Scope constraints respected: no sibling task directory and nothing under `workspace/implementation/` was read or written.

## Step 6: Generate implementation — 2026-09-02T00:12:46.934Z

Implementation complete and verified.

## Files written (25, all under `/home/ubuntu/github/CodingPRD/tasks/task_2339_food_broker_retail_authorization_slotting/workspace/implementation/`)

Top level: `start.sh` (executable), `requirements.txt` (`Flask>=2.2,<4`), `app.py`, `clock.py`, `db.py`, `errors.py`, `response.py`, `middleware.py`, `validators.py`
`services/`: `__init__.py`, `calc.py` (money math, quote ladder, amortization, void metrics, recoverable amounts), `domain.py` (cascades: acceptance, distribution recompute, at-risk evaluation, recovery hold/release, write-off, promo settlement, principal rollups)
`routes/`: `__init__.py` (13 blueprints), `retailers.py`, `principals.py`, `agreements.py`, `conflict_rules.py`, `items.py`, `reviews.py`, `presentations.py`, `deals.py`, `authorizations.py`, `snapshots.py`, `promotions.py`, `deductions.py`, `clock_route.py`

## Endpoint count: 64 (verified from Flask `url_map`, excluding `static`)
retailers 3, principals 6, commission-agreements 5, conflict-rules 4, items 5, category-reviews 7, presentations 4, slotting-deals 7, authorizations 4, distribution-snapshots 4, promotion-events 6, deductions 8, clock 1.

## Boot confirmation
`bash start.sh` boots a fresh process cleanly (flat flask-only dependency, guarded pip install, `exec python3 app.py`, no reloader, `PORT` env honored). First request after boot: `GET /retailers` → 200 with `"total_count": 0` and `api_request_timestamp: "2026-08-01T00:00:00.000Z"`, confirming the mandated logical-clock default and an empty, unseeded store. Storage is in-memory dicts only — no file or JSON persistence, no seeding, no wall-clock reads.

## Behavioral verification (two end-to-end smoke runs against live servers, since discarded)
- Quote ladder, amortization and unit cost match the SCAFFOLD worked examples (28000×100×1, forecast 200000 → admin 55000, accepted 2255000, cost/unit 11.28, FORECAST_STRAIGHT period 1 of 2 = 1127500; reversal produced -1127500 and rolled the deal back).
- Negotiation: propose/counter re-quote correctly (5000→512500, 6000→615000), round exhaustion → `ERR_INVALID_STATE`, OCC pin → 412 `ERR_STALE_PRINCIPAL_VERSION`, review reopen limit → `ERR_REVIEW_REOPEN_LIMIT`.
- Parallel-state cascades: 20% void drove `AT_RISK` + deal `RECOVERY_HOLD` + principal `WATCH`; a clean second period released the hold back to `AMORTIZING`; discontinue was blocked by a live promotion, then after cancels produced `DISCONTINUED`/`SLOTTING_WRITTEN_OFF` with `recovered 307500 + written_off 307500 = accepted 615000`.
- Demo capacity honored the changeover buffer (14:20 start rejected, 15:00 accepted against a 10:00-14:00 committed demo with buffer 30).
- Deductions: SOD enforced (`ERR_SEGREGATION_OF_DUTIES` 403 when the filer's user id approves), deny → refile → approve path resets substantiation and conserves `amount = recovered + conceded + open`, `ERR_DEDUCTION_ALREADY_SETTLED` and `ERR_DISPUTE_WINDOW_CLOSED` fire correctly.
- Envelope and band ordering confirmed for 401/403/404/400/409/412/422.

One note: the PRD/SCAFFOLD narrative order in deal-accept §3.5 conflicts with the §2.8 band table (credit posture vs. active-agreement check); band order wins in the implementation. Same precedence rule applied to snapshot uniqueness before ledger sequencing, and `ERR_SNAPSHOT_ALREADY_REVERSED` before `ERR_SNAPSHOT_NOT_LATEST`.

## Step 7: Stability sweeps and PRD-first diagnosis — 2026-09-02

Four full 8-round parallel sweeps (`--isolation per-test-server`, 362 tests per round) plus one sequential
confirmation round. Iteration 1 produced 13 genuine failures; eight fixes were applied and every subsequent
round has reported `failed: 0`.

### Test-layer fixes (`test_suite/`, 2)
- `test_04_void_rate_basis.py` — the local `two_chains_one_principal` fixture advanced the logical clock while
  finishing leg 1, so leg 2's presentation was submitted after the shared `submission_deadline` and answered
  `ERR_REVIEW_SUBMISSION_CLOSED`. The fixture now opens and submits both decks before the clock is moved to
  lock and decide. Setup-order bug in the test, not a rule change: every assertion is unchanged.
- `test_56_exclusive_operations_are_closed_to_peer_roles.py` — `assert principal["version"] == 1` contradicted
  PRD §2.4 ("A change to a *derived* field counts as a mutation ... its `version` advances"): the fixture's own
  deduction re-derives the principal's aggregates. The test now reads `version_before` and asserts the refused
  writes move nothing, which preserves the original strength.

### Implementation fixes (6, all traced to verbatim PRD sentences)
- `validators.py` + `routes/items.py` — the UPC check digit ran before the other required-field checks. PRD §2.8
  band 3 lists required fields first, and "Within a band, checks are applied in the order listed here", so
  `req_upc` was split into `req_upc_shape` (presence and twelve-digit shape) and a deferred `check_upc_digit`.
- `routes/reviews.py`, `routes/promotions.py` — client-supplied instants were normalized to three fractional
  digits. PRD §2.4 mandates that form only for `created_at`/`updated_at`; §2.5 requires payload instants merely
  to "use full ISO 8601 UTC form", and PRD line 224 says `submission_deadline` "is replaced by the supplied
  value". `req_instant_raw` now stores the caller's own text verbatim.
- `routes/deductions.py` — a `PROMO_BILLBACK` carrying no `promotion_event_id` answered band-3
  `ERR_INVALID_REQUEST`; PRD line 312 names `ERR_PROMO_LINK_INVALID` for the link rule, so both link
  requirements moved from the shape band into band 10 (same for `DUPLICATE_BILLBACK`).
- `routes/deductions.py` — `approve-recovery` and `deny-recovery` tested `dispute_state` before
  `settlement_state`; PRD §2.8 band 7 lists "both `settlement_state` and `dispute_state` on deductions" in that
  order, so a settled deduction now answers `ERR_DEDUCTION_ALREADY_SETTLED`.
- `routes/principals.py` — `GET /principals/{id}` and the commission statement had no band-5 ownership check.
  PRD §2.8 band 5: "a `PrincipalPortalUser` reading another principal's resource returns
  `ERR_PRINCIPAL_SCOPE_FORBIDDEN` (403)". `check_principal_scope` is now called after the existence lookups and
  before the band-10 agreement resolution.

No test was deleted, no assertion weakened, no fixture data seeded into the implementation.

### PRD silence left as an implementation choice
The award decision's `default_store_count` is described as optional (PRD line 253) and is only consulted "when
there is no linked deal" (line 259); the PRD names no error for an awarded item that has neither a linked deal
nor a supplied default. `decide_review` rejects that combination with `ERR_INVALID_REQUEST` rather than invent
an `authorized_store_count`. No test exercises the case.

### Residual harness noise (not a product defect)
Under host oversubscription the runner's own per-test port cleanup
(`lsof -ti:PORT -sTCP:LISTEN`, hard 5 s budget) exceeds its timeout and the affected test is recorded as a
setup error. A bare `lsof` call on this host was measured at 6.8 s with 315 sibling runners live. The count
tracked host load across sweeps (575 → 226 → 65 → 55 occurrences) and still appeared in a lone sequential
round, so it is external to this task. Across every round the reported `failed` count was 0 and no non-passing
entry carried an assertion or error-code message.

## Step 8: Finalize PRD — 2026-09-02T06:25:00.000Z

`PRD_FINALIZED.md` is written. Five inline edits, no new sections, no restructuring.

**Line counts:** PRD.md 486 → PRD_FINALIZED.md 486 (0.0% line delta; words 12,411 → 12,676, +2.1%).

**Changes**
- §2.1 (line 29) — revise — the `PrincipalPortalUser` scope enumeration now also covers reading a principal record and that principal's commission statement, and states the check is on single-resource reads only (collections the role may reach are unscoped) — `routes/principals.py:78`, `routes/principals.py:166`.
- §2.5 (line 115) — insert — client-supplied instants (`submission_deadline`, `new_submission_deadline`, `window_start`, `window_end`, and the clock echo of `current_utc`) are persisted/echoed in the caller's own text, not renormalized; only server-stamped instants carry the three-fractional-digit form — `validators.py:156`, `routes/reviews.py:45,70,142,161`, `routes/promotions.py:45,46,70,71`, `routes/clock_route.py:25`.
- §2.8 band 3 (line 146) — insert — the UPC check digit is the band's last rung, tested only after every other required field passed presence/type/range — `validators.py:223,231`, `routes/items.py:44,50`.
- §3.6 (line 255) — insert — an awarded item with no live slotting deal and no `default_store_count` is refused with `ERR_INVALID_REQUEST` (400) while store counts are resolved in `authorized_item_ids` order, outranking the slot-pool gate and a later item's `ERR_STORE_COUNT_EXCEEDS_CHAIN` — `routes/reviews.py:226-233`.
- §3.9 (line 312) — insert — the two deduction link requirements are band-10 link rules: a plainly absent `promotion_event_id`/`original_deduction_id` yields `ERR_PROMO_LINK_INVALID`/`ERR_DUPLICATE_LINK_INVALID`, supplying either under a forbidding reason code is band-3 `ERR_INVALID_REQUEST`, unknown ids are the §2.10 404s — `routes/deductions.py:63-98`.

**Per-edit pre-edit search log**
1. §2.1 principal scope — (a) subject: where `ERR_PRINCIPAL_SCOPE_FORBIDDEN` is enforced. (b) grepped `check_principal_scope` across `implementation/`: definition `middleware.py:42`; callsites `routes/items.py:83` (item read), `routes/presentations.py:74`, `routes/deals.py:128`, `routes/deductions.py:130`, `routes/principals.py:78` (principal read), `routes/principals.py:166` (commission statement); confirmed no list endpoint calls it (`list_items/list_presentations/list_deals/list_deductions/list_promotions/list_authorizations/list_snapshots/list_reviews` all unscoped) and that `GET /principals` / `GET /conflict-rules` exclude the role at band 2 instead. (c) kept an enumeration rather than a universal "any resource of another principal", and added the explicit carve-out that collections are not narrowed, so the unscoped list paths are not mis-described.
2. §2.5 instant text — (a) subject: persistence/echo form of every instant field. (b) read `clock.py` (`iso`, `parse_instant`), `validators.py:148-159` (`req_instant`, `req_instant_raw`), grepped `req_instant`/`iso_now()`: raw-text stores only at `routes/reviews.py:70,161` and `routes/promotions.py:70,71`; server-stamped `iso_now()` at `db.py:51,75`, `routes/agreements.py:131` (`activated_at`), `routes/presentations.py:158` (`submitted_at`), `routes/reviews.py:243` (`decided_at`), `routes/promotions.py:157` (`committed_at`), `routes/snapshots.py:76,163` (`posted_at`), `response.py:20`; `routes/clock_route.py:25` echoes the raw `current_utc`. Also checked date-only fields go through `req_date` + `date_str` (canonical), so they are untouched by the new sentence. (c) said "not renormalized to a canonical fractional precision" and "in the form it was supplied" instead of claiming byte-exact verbatim, since `req_instant_raw` trims surrounding whitespace while the clock echo does not; and enumerated the server-stamped fields so `posted_at`/`created_at` keep their three-digit guarantee.
3. §2.8 band 3 UPC ordering — (a) subject: UPC shape vs check-digit evaluation order. (b) grepped `req_upc`/`check_upc_digit`/`upc`: only `routes/items.py:44,50` (POST /items) enforces the digit — `req_upc` (validators.py:237) is now unused; `routes/items.py:127` uses `upc` only for the `gtin14` comparison; `upc` list filter and commission-statement `upc` ordering do no validation. (c) scoped the sentence to "on that request" / "the request's other required fields" rather than a global claim about `ERR_UPC_CHECK_DIGIT_INVALID` everywhere, since only item setup carries the field.
4. §3.6 default store count — (a) subject: resolution of `authorized_store_count` at award time. (b) read `routes/reviews.py:167-273` (the only `db.insert("authorizations", ...)` site, confirmed by grep); checked downstream consumers that assume the field exists (`routes/snapshots.py:61`, `services/calc.py:113-147`, `routes/authorizations.py:86-95`, `services/domain.py:160`) and confirmed no other path can create an authorization without a count. (c) tied the error to the per-item walk in declared order and stated exactly which two codes it outranks, instead of calling it a generic band-3 shape error (it is raised after bands 4–10 in this endpoint).
5. §3.9 deduction link rules — (a) subject: link-field presence/omission error mapping on deduction creation. (b) read `routes/deductions.py:50-123`; grepped `PROMO_LINK_INVALID`/`DUPLICATE_LINK_INVALID` — raised only in `create_deduction` (lines 84-98) and registered in `errors.py:66-67` as 422; confirmed `v.forbid` (validators.py:48) is what produces the band-3 error for the wrong reason code, and that unknown ids hit `db.get` first (`ERR_PROMOTION_NOT_FOUND` / `ERR_DEDUCTION_NOT_FOUND`); also confirmed the deduction list filters do no link validation. (c) split the sentence into three cases (absent → link error, forbidden-but-present → band 3, unresolvable → 404) so none of the three existing impl branches is mis-described.

**Deliberately left verbatim** (Step 7 items that the PRD already determines): the `approve-recovery`/`deny-recovery` ordering (§2.8 band 7 already lists "both `settlement_state` and `dispute_state` on deductions" in that order, and `routes/deductions.py:173-176,221-224,256-259,275-278` follow it uniformly), and both test-layer fixes — the `two_chains_one_principal` fixture clock bug (pure fixture setup) and the principal `version` assertion, which §2.4's "a change to a *derived* field counts as a mutation" already covers (`db.assign` bumps only when a value actually changes, `db.py:82-91`, `services/domain.py:199`).

## Step 9: Complete PRD — 2026-09-02T06:40:00.000Z

Done. `PRD_COMPLETED.md` is complete.

## Source vs. completed
| | PRD_FINALIZED.md | PRD_COMPLETED.md |
|---|---|---|
| lines | 486 | 486 (unchanged — no new sections, no new paragraphs) |
| characters | 95,998 | 104,398 (**+8,400**) |
| lines touched | — | 42 |

**Counts: 39 ambiguity-pins, 9 mismatch-revisions (48 changes total).**

## Changes

- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric chars — `response.py:10,13`
- §2.2 — insert — ambiguity — `api_request_timestamp` has 3 fractional digits and is read from the logical clock — `response.py:17-21`
- §2.2 — insert — ambiguity — unknown path → `ERR_NOT_FOUND` (404), unsupported method → `ERR_METHOD_NOT_ALLOWED` (405), both outside the §5 catalogue — `app.py:27-35`
- §2.3 — insert — ambiguity — bad/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST`; empty string = absent → default — `validators.py:245-265`
- §2.3 — revise — ambiguity — `created_at` ties broken by server write sequence — `db.py:141`
- §2.4 — insert — ambiguity — `created_at` read from the logical clock, with the `2026-08-01T00:00:00.000Z` shape — `db.py:51-53`
- §2.4 — insert — ambiguity — `version` advances once per *request*, and a no-op recompute is not a mutation — `db.py:70-95`
- §2.5 — revise — ambiguity — clock capability answers with only `current_utc`; absent/non-string/unparseable → `ERR_INVALID_REQUEST` — `clock_route.py:18-25`
- §2.7 — insert — ambiguity — each of the three version pins is an integer ≥ 0 — `deals.py:210`, `snapshots.py:39`, `reviews.py:172`
- §3.1 — insert — ambiguity — `deduction_dispute_window_days`, `demo_changeover_buffer_minutes`, `review_blackout_days` are integers ≥ 0 — `retailers.py:42-45`
- §3.1 — insert — ambiguity — PATCH principal with neither field is accepted, re-derives and still bumps `version` — `principals.py:104-116`
- §3.2 — insert — ambiguity — agreement end-date violation is `ERR_INVALID_REQUEST` (400) raised before FK resolution — `agreements.py:51-55`
- §3.2 — insert — ambiguity — `retailer_id`/`category_code` are mandatory query params; principal resolves before retailer, scope check after both — `principals.py:160-166`
- §3.2 — revise — ambiguity — line volume summed only over the qualifying authorizations; `lines` emitted in ascending `upc` — `principals.py:186-198`
- §3.3 — insert — ambiguity — `description` is a non-empty string with no maximum length — `items.py:45`
- §3.3 — insert — ambiguity — catalog strings are presence/non-emptiness only (no URL/dimension parsing); `shelf_life_days` shape-unbounded — `items.py:111-115`
- §3.3 — insert — ambiguity — `reject_reason` supplied with a `VALIDATED` decision is ignored — `items.py:150-153`
- §3.4 — revise — ambiguity — `new_item_slots` never negative — `reviews.py:46`
- §3.4 — insert — **mismatch** — blackout test runs before the two calendar-shape rules — `reviews.py:51-62`
- §3.4 — revise — **mismatch** — reopen order is window-started → calendar-invalid → reopen-limit — `reviews.py:147-158`
- §3.4 — insert — ambiguity — presentation creation has no precondition on the review's `status` — `presentations.py:41-51`
- §3.4 — revise — ambiguity — the deck's own `DRAFT` status leads the state checks (`ERR_INVALID_STATE`) — `presentations.py:106-107`
- §3.5 — insert — ambiguity — `item_count_in_scope` excess is `ERR_INVALID_REQUEST`, after the presentation resolves and before the store-count ceiling — `deals.py:84-89`
- §3.5 — insert — ambiguity — quote already evaluated at creation; no presentation-status precondition; "live deal" = earliest-created `PROPOSED`/`COUNTERED` — `deals.py:82,117`, `reviews.py:218-221`
- §3.5 — revise — **mismatch** — counter tests `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` before `ERR_COUNTER_NOT_HIGHER` — `deals.py:190-193`
- §3.5 — revise — **mismatch** — accept order: pin → deal state → offeror → review → presentation → principal → agreement → credit posture → budget — `deals.py:224-251`
- §3.6 — revise — ambiguity — `authorized_item_ids` mandatory, duplicate-free, ≤ 1,000; `default_store_count` integer ≥ 0 — `reviews.py:173-174`
- §3.6 — revise — ambiguity — a terminated principal's item reports `ERR_ITEM_NOT_IN_SUBMITTED_PRESENTATION` — `reviews.py:202-204`
- §3.6 — insert — ambiguity — fresh authorization field seeds plus basis-dependent store counters; never born `AT_RISK` — `reviews.py:250-272`, `calc.py:118-139`
- §3.6 — revise — ambiguity — hop-2 share ordering breaks a remaining tie by write sequence — `domain.py:314`
- §3.7 — insert — ambiguity — posting requires `AUTHORIZED` or `AT_RISK`, else `ERR_INVALID_STATE`, straight after the pin — `snapshots.py:51-52`
- §3.7 — revise — **mismatch** — `ERR_PERIOD_ALREADY_POSTED` is tested before `ERR_PERIOD_OUT_OF_SEQUENCE` — `snapshots.py:54-58`
- §3.7 — revise — ambiguity — `amortized_amount_cents` is 0 (and the deal untouched) when the deal is not `AMORTIZING`/`RECOVERY_HOLD` — `domain.py:238-241`
- §3.7 — revise — ambiguity — no-live-posting counters spelled out per basis — `calc.py:118-139`
- §3.7 — revise — ambiguity — reversal copies the two store counts and the case volume, own `is_reversed` false — `snapshots.py:152-165`
- §3.7 — revise — **mismatch** — already-reversed precedes not-latest; `periods_reported` floored at 0; rollback only when that posting amortized to that deal — `snapshots.py:143-171`, `domain.py:260`
- §3.7 — revise — **mismatch** — reversal re-takes the at-risk decision in *both* directions (may also enter `AT_RISK`/`RECOVERY_HOLD`) — `snapshots.py:174-179`
- §3.7 — insert — ambiguity — voids report gives `latest_period_index`/`reported_store_count` as 0 with no live posting; `is_at_risk` mirrors state — `authorizations.py:96-103`
- §3.7 — insert — ambiguity — discontinue leaves the distribution counters and `void_rate_bps` untouched — `authorizations.py:127-135`
- §3.8 — revise — ambiguity — `window_end` violation is `ERR_INVALID_REQUEST` (400) before the authorization resolves — `promotions.py:57-63`
- §3.8 — revise — ambiguity — `sample_units_requested` optional ≥ 0 for non-demo types; planning has no authorization-state precondition — `promotions.py:55,63`
- §3.8 — revise — ambiguity — commit checks the event's own `PLANNED` state first — `promotions.py:116-117`
- §3.9 — revise — ambiguity — `claim_amount_cents` ≥ 0; dispute requires `dispute_state` `NOT_DISPUTED`/`DENIED` else `ERR_INVALID_STATE` — `deductions.py:169-176`
- §3.9 — revise — ambiguity — `document_ref` required but never persisted; other dispute states → `ERR_INVALID_STATE`; `settlement_state` not consulted — `deductions.py:202-210`
- §3.9 — revise — **mismatch** — approval order: settled → `SUBSTANTIATED` → segregation → document count — `deductions.py:220-229`
- §3.9 — revise — **mismatch** — denial order: settled → `SUBSTANTIATED` → segregation — `deductions.py:255-262`
- §3.9 — insert — ambiguity — refile bound tested after the dispute window and before the claim ceiling — `deductions.py:178-185`
- §3.9 — revise — ambiguity — concede checks settled first; `FILED`/`APPROVED` refused with `ERR_INVALID_STATE` — `deductions.py:275-278`

Deliberately *not* changed: per-endpoint "wrong state → `ERR_INVALID_STATE`" cases already generically pinned by §2.8 band 7, and check orders that fall out of the band ladder without contradicting the §3 narrative.
