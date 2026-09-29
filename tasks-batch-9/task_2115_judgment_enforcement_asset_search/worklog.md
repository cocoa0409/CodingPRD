# Worklog — task_2115_judgment_enforcement_asset_search

## Step 1: Create task directory — 2026-08-17T03:12:48.729311654Z

Created `./tasks/task_2115_judgment_enforcement_asset_search/` and `workspace/` subdirectory (next index after task_2114_furniture_bank).

## Step 3: Copy shared files — 2026-08-17T03:13:04.418482330Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 2: Generate scaffold — 2026-08-17T04:09:38.940620455Z

All three artifacts are generated and pass the skill's lint clean.

## Files written
- `SCAFFOLD.yaml` (§1.0–§1.7) — 2855 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`) — 1969 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`) — 3478 lines

## Lint verdict (pasted verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
Coverage
  §1.5 endpoints declared:    49
  §1.1 entities declared:     11
  §1.8 instances scanned:     26
  §1.9 instances scanned:     67
  Calls scanned (§1.8+§1.9):  808

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Design summary
- **Profile**: compliance_audit x ledger_reconciliation, `expert_plus`, **flat** topology (no URL nesting; `api_prefix: ""`), **cyclic** state-machine shape, **segregation_of_duties** role model, layers = optimistic_concurrency / dual_variant_calculation / cascading_side_effects / rate_threshold_triggers. Deliberately targets the diversity gaps the skill flags (flat, cyclic, self-referential, segregation-of-duties are all 0% in the skill's examples).
- **Surface**: 11 entities, 11 state machines, 3 OCC concurrency rules, 8 calculations, 42 ordered validations, 49 endpoints, 49 errors, 6 roles.
- **Non-linear machines**: `Judgment` and `DebtorExamination` each carry two independent state dimensions on one row; cycles on `Judgment.enforcement_posture` (ENFORCING<->STAYED, ENFORCING<->LIEN_PERFECTED), `CountyFiling` (SUBMITTED<->REJECTED), `EnforcementAction` (SERVED<->SUSPENDED), `InstallmentAgreement` (ACTIVE<->DEFAULTED); `ExemptionClaim` branches with divergent side-effect sets.
- **§1.8**: 26 instances across all nine `rule_id`s (min 2 each). Every formula-derived assertion is a literal computed in Python against the scaffold's own formulas — e.g. payoff `4299064` (STATUTORY_ORDER) vs `4293767` (PRINCIPAL_FIRST) on identical payment history; contingency fee `495034` per-payment vs `495033` aggregate; garnishment `0` at exactly 21750 vs `1` at 21751; renewal capitalizing to principal `9756164`.
- **§1.9**: 80 instances (67 with executable recipes, 13 `excluded_because` stubs) walking all nine claim-extraction-guide sections.
- **Notable §1.5 reshapes forced by the design pass**: a `/_clock/set_current_utc` ops-sweep endpoint (default `2026-08-01T00:00:00Z`, four pinned sweep steps), filtered-list GETs for every FK including the self-referential `responds_to_offer_id`, and `GET /installment-agreements` as the sole discovery channel for the cascade-created agreement.
- **Determinism fixes made during the pass**: `AssetFinding.swept_cents` added so `available + frozen + swept == estimated_value` holds at every instant; lien priority now renumbers the whole county cohort by `(recorded_on, created_at)`; `ERR_OPPOSITION_WINDOW_CLOSED` was removed as unreachable once the clock sweep owns the opposition deadline.

No sibling task directory was read, listed, or grepped.

## Step 4: Generate PRD — 2026-08-17T04:23:28.645709684Z

PRD generated at `workspace/PRD.md` (431 lines, 94 KB). Neither design file was opened, grepped, or referenced.

## Hard Contract Reports

```
Field coverage check:
- entities[].fields:            109 required, 109 present, 0 missing
- endpoints[].request_body:      52 required,  52 present, 0 missing
- endpoints[].query_params:      18 required,  18 present, 0 missing
- endpoints[].path_params:       10 required,  10 present, 0 missing
- endpoints[].output keys:       15 required,  15 present, 0 missing
- TOTAL unique identifiers:     135 required, 135 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority:   42 checked, 42 expressed in ordered prose (§2.8), 0 missing
- concurrency_rules[] OCC:        3 checked,  3 expressed (write_endpoint + expected_<parent>_version + error_id + 412), 0 missing
- state_machines[].transitions:  51 checked, 51 fully expressed with explicit `FROM -> TO` arrow pairs, 0 missing
- calculations[]:                 8 checked,  8 fully expressed (no pseudocode, no fuzzy words), 0 missing
- validations[] conditions:      42 checked, 42 matchable to error_id in prose, 0 missing
- endpoints side_effects/applies_to: 49 checked, 49 expressed, 0 missing
- entities[].fields structured content: 109 checked, 109 reconstructible (defaults/initials/nullability), 0 missing
- sibling-branch symmetry:        6 groups checked (SUSTAINED|OVERRULED, STATUTORY_ORDER|PRINCIPAL_FIRST, PRELIMINARY|CERTIFIED, HELD|NO_SHOW|CONTINUED, RELEASE from 3 states, SATISFIED|EXPIRED cascades), 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 829
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Coverage counts (self-audit)

| Scaffold section | Declared | In PRD |
|---|---|---|
| §1.1 entities | 11 | 11 |
| §1.2 state machines / transitions | 11 / 51 | 11 / 51 |
| §1.2.1 concurrency rules | 3 | 3 |
| §1.3 calculations | 8 | 8 |
| §1.4 validations | 42 | 42 |
| §1.5 endpoints | 49 | 49 |
| §1.6 errors | 49 | 49 |
| §1.7 roles | 6 | 6 |
| state enum values / field enum values | 38 / 68 | 38 / 68 |

No truncation: §2.2 matches the canonical block byte-for-byte, §4 has 49 rows / 4 columns, §5 has 49 rows / 2 columns, file ends at §5 with no audit footer.

## Two issues found in SCAFFOLD.yaml that needed a judgement call

**1. Five constants are referenced but never numerically defined anywhere in SCAFFOLD.yaml.** They appear only as symbolic names in `entities[].fields[].description`, `state_machines[].transitions[]`, `validations[].check`, `errors[].condition`, and `endpoints[].side_effects` — no `calculations[].constants` block assigns them values. Omitting them would leave `filing_deadline_on`, `opposition_deadline_on`, `subpoena_service_deadline_on`, the exam cooling rule and the continuance cap unimplementable, so values were pinned in the prose:

| Constant | Value written into the PRD | Where |
|---|---|---|
| `EXEMPTION_RESPONSE_DAYS` | 20 days | §3.6 |
| `OPPOSITION_RESPONSE_DAYS` | 10 days | §3.6 |
| `SUBPOENA_LEAD_DAYS` | 10 days | §3.4 |
| `EXAM_COOLING_DAYS` | 120 days (stated also as 2,880 hours) | §2.8, §3.4 |
| `MAX_CONTINUANCES` | 2 | §3.4 |

If the withheld design files pin different numbers, these five figures in the PRD must be reconciled before the test suite is generated.

**2. Three date-window preconditions carry no `error_id` in the scaffold**: `recorded_on` within `[submitted_on, current clock date]` on filing adjudication, `served_on` within `[writ_requested_on, current clock date]` on writ service, and `served_on` within `[current clock date - 30 days, current clock date]` on examination service. `ERR_PAYMENT_DATE_INVALID` covers only payments. All three mapped to `ERR_INVALID_REQUEST` (400), stated explicitly in §3.2, §3.4 and §3.5.

Also worth noting: `validations[]` numbering skips priority 22 (goes 21 -> 23), so the 42 rules are renumbered 1-42 in the PRD's §2.8 ladder while preserving the scaffold's relative order exactly.

## Step 6: Generate implementation — 2026-08-17T04:54:01.75479007Z

All 49 endpoints and all 49 error codes match the PRD exactly. Implementation is complete and verified.

## What was built

`workspace/implementation/` (2925 LOC Python)

```
start.sh          guarded pip install + exec python3 app.py (foreground, 0.0.0.0:$PORT, default 10000)
app.py            Flask entry point, error handlers
store.py          in-memory dicts + logical clock (2026-08-01T00:00:00Z) + monotonic created_at
errors.py         49-code catalogue with HTTP statuses
envelope.py       meta/response_type/data envelope, req_XXXX ids, ms-precision timestamps
auth.py           X-User-ID / X-User-Role, six roles, entity-backed ownership
validators.py     rung 7-10 shape/enum/sign/pagination checks
domain.py         constants, payoff replay, scores, garnishment/levy, priority, cascades, sweep
web.py            route decorator (global lock, auth, envelope)
routes/*.py       11 modules, 49 endpoints
```

Boots cold in ~550 ms with an empty store on every invocation; no seeding anywhere (verified by repeated kill/restart cycles).

## Decisions worth flagging

- **Replay cost seed excludes renewal fees.** PRD §3.8 says costs start with "a renewal fee for each renewal already taken" *and* the walk adds 5,000 cents at each renewal event — taken literally that double-counts. Costs seeded as `filing_costs + recorded filing fees + sheriff fees`, letting the walk add renewal fees; the only reading consistent with §3.9's direct `costs += RENEWAL_FEE_CENTS` at renewal. Verified: a post-renewal replay reproduces the renewal-time balances exactly.
- **`active_enforcement_count` is recounted, not incremented.** §3.5 says serve increments it, but the row was already counted at writ request and the field is defined as a count of `WRIT_REQUESTED|SERVED|SUSPENDED`. All three judgment counters (plus `collected_to_date_cents`, `active_judgment_count`) are recomputed from their definitions.
- **`current_utc` echoes the raw `to_iso8601` string** (PRD: "echoes the new logical instant"); input-sourced datetimes (`scheduled_at`, `expires_at`, `entered_on`) are likewise echoed, computed instants (`decided_at`) use the canonical `.SSSZ` form.
- **Payment splits are recomputed for every payment on each persisting replay**, not only the new one — required for out-of-order bookings to reconcile with the replayed balances.
- **Debtor `version` bumps on exactly the four operations in §2.4**; writ request and quash-driven score recomputes refresh `updated_at` only.
- **Filing an exemption claim against a writ with no `served_on` -> `ERR_INVALID_STATE`** (the window check is undefined without `served_on`).
- List reads are ownership-scoped (not 403'd) for `Creditor`/`Debtor` across all child collections, extending §2.1's explicit judgment scoping.

## Verification

~200 assertions across 7 scripted suites, each run against a freshly booted server: interest segment rounding vs. hand-computed replay, PRINCIPAL_FIRST/STATUTORY_ORDER divergence, renewal capitalization and the 2-renewal limit across decade-long clock jumps, contingency tier boundaries with per-payment rounding, custody conservation through serve/release/quash/collect, the levy occupation-window conflict, cohort-wide lien priority renumbering with demotion, both segregation-of-duties rules, all three OCC guards, the stay/default/reinstate cycle, and all four docket-sweep steps with their counts.

## Step 5: Generate unit tests — 2026-08-17T04:54:34.652955583Z

Test infrastructure and suite generated. Summary:

## What was produced

**`test_helpers/`** (9 files) — `types.py` (17 status enums + 11 entity TypedDicts, all carrying `id`/`created_at`/`updated_at`/`version` since PRD §2.4 declares the full common set for every entity), `api_client.py` (46 endpoint methods), `api_errors.py` (49 error IDs registered with the framework's status map), `assertions.py` (per-entity assertions + custody-conservation, ledger-identity, installment-schedule and payoff-quote invariant checkers), `factories.py`, `constants.py`, `test_users.py` (opaque-staff builders plus mandatory per-instance `make_creditor_headers` / `make_debtor_headers` for the two `entity_backed` roles), `fixtures.py` (~490 lines, 6 tiers up to `setup_stayed_judgment`, `setup_opposed_exemption_claim`, `setup_defaulted_agreement`).

**`test_suite/`** — `conftest.py` + 11 domain-named files, **115 tests**, all collected clean by pytest and clean under pyflakes.

## Coverage against the two design indices

- **Queue A (difficulty):** 25 of 26 instances x exactly 2 tests = 50 tests.
- **Queue B (corner):** 63 of 65 non-stub instances x 1 test = 63 tests. All 13 `excluded_because:` stubs verified to resolve to real difficulty instances; none translated.
- Every docstring ends with exactly one verbatim `Design:` tag; an automated pass confirmed every quoted PRD citation survives a whitespace-normalised literal match against `PRD.md`, and that every tag resolves.

## Skips — all three are the reported cross-artifact constant hazard

| Instance | Constant | Design value | PRD value |
|---|---|---|---|
| `Difficulty/resource_temporal_overlap/exam_symmetric_thirty_day_buffer_on_debtor` | `EXAM_COOLING_DAYS` | 30 days (accepts 2026-10-01, 30 days out) | 120 days / 2,880 hours — that same instant would be **rejected** |
| `Corner/validations/exemption_claim_filed_after_the_window_returns_window_closed` | `EXEMPTION_RESPONSE_DAYS` | `filing_deadline_on` = served_on + 15 -> 2026-08-16 | 20 days -> 2026-08-21 |
| `Corner/validations/exemption_claim_filed_on_the_deadline_day_is_accepted` | same | same | same |

Knock-on: `ERR_EXAM_COOLING_PERIOD` now has no test at all, because the only corner instance for it (`errors/exam_cooling_period_error_is_triggerable`) is a stub pointing at the skipped difficulty instance. `ERR_EXEMPTION_WINDOW_CLOSED` is likewise untested. These are gaps left as gaps, per instruction.

## Other design assertions deliberately not encoded (two-reader failures, not constant taint)

- **`active_enforcement_count` values and the `ENFORCING -> LIEN_PERFECTED` step-back.** The PRD increments this counter **twice** for one action (once at §3.5 writ request, again inside the service branch), yet §3.9 states it "stands at 0" after all actions release. Two faithful PRD-only readers reach different numbers, and the posture step-back is gated on the count reaching 0 — so no test asserts either. All affected instances keep their remaining assertions (cascade hops, custody, statuses).
- **`Creditor.active_judgment_count`** (asserted by 4 corner instances): there is no `GET /creditors` endpoint in PRD §4, so the field is unobservable through the API.
- **`perfected_county_count == 2`** after an out-of-state recording: PRD gates the *posture* move on the state match but leaves open whether the counter increments for an out-of-state filing.
- **`decided_at == <exact sweep instant>`** on a swept offer, and **`updated_at == created_at`** at creation: PRD stamps both but never pins the value.

## One design-recipe bug worked around

`Corner/cross_cutting_complexity_layers/stale_debtor_version_on_skip_trace_returns_412` sends `hits_count: 0` in its trigger. Under PRD §2.8 the sign check (rule 9) fires before the OCC check (rule 13), so that recipe would yield `ERR_NON_POSITIVE_AMOUNT`, not the asserted code. The test uses a positive `hits_count` so only the stale-version check can fail — preserving the instance's asserted outcome.

All arithmetic in the design indices was independently re-derived (interest segments, both application orders, contingency slices, levy holds, the 180-day renewal window, both recoverability variants) and matched exactly; the design's literal values are copied verbatim.

## Step 7: Run tests and iterate — 2026-08-17T05:03:03.858415032Z

All 8 parallel rounds pass 115/115. Done.

## Summary

**Iterations run: 2** (two full 8-round parallel stability sweeps).

**Sweep 1** — 113/115 in all 8 rounds, with the *same* 2 tests failing in *every* round (fully deterministic, no flakiness anywhere in the suite):
- `test_10_renewal_expiry_and_the_clock.py::test_the_clock_may_not_be_wound_backwards`
- `test_10_renewal_expiry_and_the_clock.py::test_a_quiet_clock_advance_reports_five_zero_counters`

Both tripped on the identical assertion: `assert summary["current_utc"] == "2026-09-01T00:00:00.000Z"` vs. the server's `"2026-09-01T00:00:00Z"`.

**Sweep 2** — 115/115 in all 8 rounds.

### Tests deleted
None. The two failures resolved under STEP 1c (partial coverage), not STEP 1a/1b wholesale deletion.

### Fixes applied to `test_helpers/`
- `test_helpers/assertions.py` — added `assert_logical_instant_equals(value, expected_iso, field_name)`: asserts the value is a well-formed ISO 8601 instant carrying a UTC designator **and** that it denotes exactly the expected instant, without constraining fractional-digit width. Verified it still rejects a wrong instant, a bare date, a non-string, and malformed text.

### Fixes applied to `test_suite/`
- `test_suite/test_10_renewal_expiry_and_the_clock.py` (3 assertions, lines 216/225/252) — replaced the `.000Z` string-literal comparison with `assert_logical_instant_equals`.

### Fixes applied to `implementation/`
None. No implementation check was removed, weakened, or added.

### Why this was a test bug, not an implementation bug (STEP 1c rationale)
- **Covered, kept at full strength:** PRD §2.5 — *"`current_utc` echoes the new logical instant"*, plus the five sweep counters, the `ERR_CLOCK_REGRESSION` rejection, and the "may stay where it is" re-set. Every one of these assertions survives unchanged.
- **Uncovered, removed:** the three-fractional-digit rendering. PRD pins that width in exactly two places, neither of which reaches this field — §2.2 binds `api_request_timestamp`, and §2.4 binds `created_at`/`updated_at` **on stored objects**, while §2.5 states outright that the clock response *"is not a stored object but a summary"*. `grep` for "fractional" over PRD.md returns only those two plus an unrelated rounding sentence.
- **Two-reader experiment (unique derivability fails):** Reader A echoes the supplied string `2026-09-01T00:00:00Z` — literally "echoes", and matching PRD §2.5's own rendering of a logical instant, `2026-08-01T00:00:00Z`, which carries no fractional digits. Reader B normalizes to `.SSSZ` by analogy with §2.2. Both are PRD-faithful, so the `.000Z` literal is not uniquely derivable and could not stand.

### Feedback for the upstream generators
- **doc-generator (Zero-Silence violation):** PRD §2.5 names `current_utc` and its semantics but never pins its serialization format, while §2.4's three-digit rule is explicitly scoped away from it by the phrase "not a stored object". Either state the rendering for `current_utc` or drop the format-bearing example.
- **unit-test-generator (unique-derivability miss):** design instances `Corner/validations/setting_the_clock_backwards_returns_clock_regression` and `Corner/endpoints/clock_endpoint_reports_zero_sweep_counts_when_nothing_is_due` both encoded a literal `.000Z` for `current_utc` that no PRD sentence supports — a timestamp-rendering assertion generated by analogy with envelope fields rather than from PRD prose.

One note on the earlier hazard flags: the three constants the implementation generator flagged as ambiguous (`active_enforcement_count` double-increment, replay cost seeding excluding renewal fees, the `ENFORCING -> LIEN_PERFECTED` step-back) never surfaced as failures — the test generator had already declined to encode assertions on them, so those PRD ambiguities remain untested rather than mis-tested.

## Step 8: Finalize PRD — 2026-08-17T05:05:57.422757100Z

Done. `PRD_FINALIZED.md` written at `workspace/PRD_FINALIZED.md`.

## Size

- PRD.md: 430 lines / 94,310 chars
- PRD_FINALIZED.md: 430 lines / 94,487 chars
- Line delta: 0 lines (0.000%); character delta +177 (+0.184%). One line revised (line 97), no lines added or removed, no new sections.

## Changes

- **§2.5 (The Logical Clock and the Docket Sweep)** — revise — `current_utc` now states its rendering: it reproduces the caller's `to_iso8601` string exactly as supplied, with no renormalisation of fractional-second digits or of the UTC designator — `implementation/routes/clock_routes.py:15,23,25` (`raw = require_string(body, "to_iso8601")` ... `data = {"current_utc": raw}`).

## Pre-edit search log

**Edit 1 — §2.5 `current_utc` rendering**

(a) **Subject identified:** serialization/rendering of datetime-valued response fields, specifically the clock summary's `current_utc`; by extension every datetime-rendering class the implementation exhibits.

(b) **Impl paths enumerated (read/grepped):**
- Producer of `current_utc` — `routes/clock_routes.py:13-27`. `raw` is the unparsed request string; `parse_instant` is used only for the regression comparison and for `store.clock`. Response carries `raw` verbatim. Grep confirmed this is the *only* producer (`grep -rn "current_utc"` -> one hit) and `routes/__init__.py` confirms one clock route, POST-only, so `current_utc` is never emitted for the un-advanced initial clock.
- `store.clock_raw` — `store.py:41`, `routes/clock_routes.py:23`. Written but read nowhere else, so `INITIAL_CLOCK_RAW = "2026-08-01T00:00:00.000Z"` is unobservable and does not contradict §2.5's `2026-08-01T00:00:00Z` prose. Left untouched.
- Envelope timestamp — `envelope.py:17-19`: always `%Y-%m-%dT%H:%M:%S` + exactly 3 digits + `Z`. Matches §2.2 line 47 as written.
- Stored `created_at`/`updated_at` — `store.py:50-61` (`now_iso`), `new_row`/`touch`/`bump` at `store.py:80-103`: always 3 fractional digits. Matches §2.4 line 82 as written.
- Computed instant `decided_at` — `domain.py:566-572` (`instant_string`/`clock_instant_string` -> `store.fmt_instant`, 3 digits), used at `domain.py:542` (sweep expiry) and `routes/offer_routes.py:128, 173, 203, 220`. PRD is silent on its width; **not touched**, as it is outside the Step 7 scope.
- Input-echoed instants — `routes/exam_routes.py:76` (`scheduled_at`) and `:172` (`new_scheduled_at` overwrite), `routes/offer_routes.py:116` (`expires_at`): stored as the raw body string, *not* renormalised (the parsed copy lives in `_expires_at`, a private `_`-prefixed field stripped by `store.public`).
- Input-normalised dates — `routes/judgment_routes.py:83,85` (`entered_on`, `expires_on` via `date.isoformat()`), and every `*_on` field elsewhere, all rendered `YYYY-MM-DD` via `fmt_date`/`.isoformat()`. `validators.parse_date` accepts a full instant and truncates to the date, so these are genuinely normalised, unlike the echoed instants.

(c) **Wording adjustment made:** the first draft contrasted `current_utc` against "the three-fractional-digit form used for stored timestamps." The enumeration showed that claim would be false as a universal — `scheduled_at` and `expires_at` are stored instants that are *not* three-digit-normalised — so a reader could derive a wrong rule for those two fields. The contrast clause was dropped entirely and the sentence re-scoped to name only `current_utc` and its own source field `to_iso8601`, describing the rendering positively rather than by comparison. No other section was edited, so §2.2's `api_request_timestamp` rule and §2.4's `created_at`/`updated_at` rule remain verbatim.

Note on what was deliberately *not* changed: `decided_at`'s three-digit rendering is also PRD-unpinned, but no Step 7 fix touched it, so under the hard scope rule it was left alone.

## Step 9: Complete PRD — 2026-08-17T05:15:56.208032147Z

Done. `PRD_COMPLETED.md` written.

**Files**
- Source: `workspace/PRD_FINALIZED.md` — 430 lines, 94,487 chars
- Output: `workspace/PRD_COMPLETED.md` — 430 lines, 101,160 chars (**+6,673 chars**)
- Line count and section count (25 headings) unchanged — all edits are in-paragraph; no new sections, no new paragraphs.

**Counts:** 24 changes — 13 ambiguity-pins, 11 mismatch-revisions.

**Changes**
- §2.1 — insert — ambiguity — list reads for entity-backed callers are a *narrowed result set* (with `total_count` post-filter), never `ERR_NOT_RESOURCE_OWNER`, and the narrowing covers filings/actions/claims/offers/agreements/payments, not just judgments — `routes/helpers.py:11-14`
- §2.4 — insert — ambiguity — `updated_at` == `created_at` at creation; both stamped from real wall clock (not the logical clock) and strictly increasing; rendering rule by provenance: server-computed instants get canonical 3-digit `Z`, client-echoed datetimes stored verbatim, `*_on` fields normalised to bare `YYYY-MM-DD` — `store.py:50-61,71-73,80-96`
- §2.4 — insert — ambiguity — judgment `version` list extended with "when an enforcement action is drafted against it" — `routes/enforcement_routes.py:90`
- §2.4 — insert — ambiguity — events that refresh `updated_at` only: certified-score stamp at writ request, quash-driven score recompute, offer rejection/expiry, non-moving writ release — `routes/enforcement_routes.py:151-156`, `domain.py:450-455`
- §3.1 — insert — ambiguity — creditor counter is recomputed (never delta'd) and each recompute bumps the creditor row's own `version` — `domain.py:192-197`, `routes/judgment_routes.py:109-110`
- §3.1 — revise — mismatch — docketing "increments `active_judgment_count` by one" -> recomputed from definition — `routes/judgment_routes.py:109-110`
- §3.1 — revise — mismatch — "no `last_skip_trace_on` at all" -> field present but null — `routes/party_routes.py:83`
- §3.2 — revise — mismatch — `perfected_county_count` recomputed as count of `RECORDED` filings **regardless of state**; posture moves `NONE -> LIEN_PERFECTED` gated on posture==`NONE` **and** filing state == debtor state, not on the count rising 0->1 — `routes/filing_routes.py:166-172`, `domain.py:186-189`
- §3.2 — insert — ambiguity — priority renumbering bumps only cohort members whose `priority_rank` actually changes; unchanged members untouched; the recorded filing takes one bump — `domain.py:385-395`
- §3.3 — insert — ambiguity — the finding row itself keeps `weekly_disposable_earnings_cents`, null for non-employment classes — `routes/asset_routes.py:247`
- §3.4 — insert — ambiguity — `CONTINUED` leaves `subpoena_status` where it stands and `outcome_recorded_on` unstamped — `routes/exam_routes.py:317-323`
- §3.5 — revise — mismatch — writ request: `active_enforcement_count` recomputed from `WRIT_REQUESTED|SERVED|SUSPENDED` (not incremented); judgment `version` does not move, only `updated_at` — `routes/enforcement_routes.py:151-156`, `domain.py:176-181`
- §3.5 — revise — mismatch — service: counter recomputed and therefore **unchanged** (removes PRD's second increment) — `routes/enforcement_routes.py:212-217`
- §3.5 — revise — mismatch — release: counter recomputed rather than decremented — `routes/enforcement_routes.py:229-232`
- §3.5 — revise — mismatch — `collected_cents` rises on any payment naming the action, collecting or not; collection additionally requires status `SERVED` — `routes/payment_routes.py:204-223`
- §3.5 — insert — ambiguity — step-back gated on three recomputed conditions (posture exactly `ENFORCING`, count 0, `perfected_county_count` >= 1); `version` moves only when the posture actually steps back, else `updated_at` only — `domain.py:411-420`
- §3.6 — insert — ambiguity — claim against a writ with no `served_on` -> `ERR_INVALID_STATE`; the test is the stamp alone, so a since-released/collected/quashed action still accepts a claim — `routes/exemption_routes.py:59-60`
- §3.6 — revise — mismatch — SUSTAINED cascade also recomputes the debtor's preliminary score (`updated_at` only); counter recomputed; a ruling on an action already out of `SERVED`/`SUSPENDED` still stands and unwinds nothing — `domain.py:437-455`
- §3.6 — revise — mismatch — DEFAULTED branch counter recomputed, same three step-back conditions — `domain.py:529-536`
- §3.7 — insert — ambiguity — countering a non-`OPEN` parent is `ERR_INVALID_STATE`; `decided_at` uses the canonical 3-digit `Z` form, not the raw clock echo — `routes/offer_routes.py:88-89,126-129`, `domain.py:566-572`
- §3.8 — revise — mismatch — replay cost seed is `filing_costs + recorded filing fees + sheriff fees` **only**; renewal fees are added by the walk, never pre-seeded (removes the double count) — `domain.py:203,245`
- §3.8 — insert — ambiguity — quote echoes `as_of` normalised to `YYYY-MM-DD`; `collected_to_date_cents` is the judgment's stored figure, so `gross_exposure_cents` = quoted payoff + stored collection — `routes/judgment_routes.py:152-163`
- §3.8 — revise — mismatch — reversal: counter recomputed (not incremented); custody is **not** rewound — swept cents stay swept, `levy_hold_cents` stays 0 — `routes/payment_routes.py:282-300`
- §4 — insert — ambiguity — the object in `data` is always the resource named in the path, never the judgment or cascade-created row — `routes/filing_routes.py:173`, `routes/offer_routes.py:208`, `routes/agreement_routes.py:71`, `routes/party_routes.py:140`

**Verified as already correctly pinned (no change):** all five doc-generator constants (`EXEMPTION_RESPONSE_DAYS=20`, `OPPOSITION_RESPONSE_DAYS=10`, `SUBPOENA_LEAD_DAYS=10`, `EXAM_COOLING_DAYS=120`/2,880 h, `MAX_CONTINUANCES=2`) match `domain.py:39-44`; the 42-rung screening order matches the route check sequences; error->HTTP catalogue matches `errors.py`; recoverability variants, garnishment/levy caps, contingency tiers, settlement floor, agreement schedule maths, and the sweep's four-step order all match.

