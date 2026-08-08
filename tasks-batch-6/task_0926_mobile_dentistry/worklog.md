# Worklog — task_0926_mobile_dentistry

Scenario (verbatim): `926. Mobile Dentistry (schools/SNF): site & consent roster, portable-equipment & staff scheduling, screening/exam & varnish/sealant, treatment-plan & referral, insurance/Medicaid & sliding fee, parent/facility report, follow-up, program reporting`

Difficulty parameter: **beyond-Expert** (user request: "generate task hard than expert level!"). This is an input parameter to the Step-2 scaffold-generator only; it does not limit pipeline scope. Full pipeline Steps 1–9 runs to completion.

## Step 1: Create task directory — 2026-08-04T03:59:46.000Z

Created `tasks/task_0926_mobile_dentistry/workspace/`. Index 0926 = max existing (0925) + 1.

## Step 3: Copy shared files — 2026-08-04T03:59:46.000Z

Copied `INSTRUCTION.md` → `tasks/task_0926_mobile_dentistry/workspace/INSTRUCTION.md` (1424 bytes). Done early alongside Step 1 (no dependency on Step 2).

## Step 2: Generate scaffold — 2026-08-04T05:02:00.000Z

All three scaffold artifacts are complete and audited.

### Files written
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

### Density (beyond-Expert targets all met)
| Dimension | Target | Delivered |
|---|---|---|
| Entities | 14–16 | **15** |
| Endpoints | 60–70 | **70** |
| SM axes | 10–13, ≥8 non-linear | **13, all 13 non-linear** |
| Error codes | 30–36 | **36** |
| Ladder rungs | 20+ | **38** |
| Calculations | 12+, ≥5 dual-variant | **21, 5 dual-variant** |
| OCC rules | 2–3 | **3** (Patient, SiteVisit, Encounter) |
| Conservation invariants | 3–4 | **4** (money / chair-minutes / varnish count / consent-tier cardinality) |
| Cascade depth | 5 | **5** (spore FAILED → TAINTED → reprice-revert → SUPERSEDED plan → ABANDONED referral), plus depth-3 consent-downgrade and depth-3 report-submit chains |

Non-linear shapes used: cycles (ProgramPeriod, Site, PortableUnit, Coverage, Referral, Report), self-loops (Consent SNF reaffirmation, SiteVisit reschedule, TreatmentPlan follow-up, Report regenerate), parallel axes on one row (Encounter clinical × billing), branch-with-divergent-side-effects (SterilizationLoad PASSED vs FAILED), three-way terminal fan-outs (Consent, Procedure, TreatmentPlan).

### Constants
**54 declared, 0 undeclared** — confirmed by grepping every ALL_CAPS token in SCAFFOLD.yaml and resolving it against `calculations[].constants`, a new top-level `global_constants:` block, `validation_gate_scopes:`, entity enum constraints, state names, error ids, and a new `request_enums:` block.

### YAML lint
`python3 -c "import yaml,sys; [yaml.safe_load(open(p)) for p in sys.argv[1:]]" <3 files>` → **all three safe_load clean**. Two parse failures were hit and fixed en route: bare `?`-suffixed optional field names inside flow sequences (`input: [...]`) and bare `[` inside flow mappings (`$.data[0].id`, `grounds: [errors[X]]`) — all now quoted.

`scaffold_lint.py` → **VERDICT: clean lint**, 1066 calls scanned across 66 active instances.

### Reachability defects found and fixed
1. **`ERR_REFERRAL_NOT_DUE` was unreachable.** `SENT → NO_RESPONSE` required `clock >= next_eligible_send_at`, so no referral could ever be in NO_RESPONSE *and* too early to re-send. Fixed by removing the timing precondition from the NO_RESPONSE entry leg (the waiting period now lives only on the re-send rung), with a `note:` recording why.
2. **`ERR_MEDICAID_BALANCE_BILL` was unreachable.** Medicaid patient responsibility is always 0 by formula, so the rung could never fire. Fixed by adding an optional `manual_patient_responsibility_cents` override on the price endpoint that rung 37 refuses for Medicaid coverage.
3. **`ERR_SLIDING_FEE_MISSING` was unreachable** at pricing time (verify already guarantees a band). Re-scoped to the coverage-verify endpoint, where an UNINSURED patient with null income is genuinely reachable.
4. **`ERR_PROCEDURE_TAINTED` had no scope.** Given as a rung with no endpoint; scoped to price/claim on an encounter with `tainted_procedure_count > 0`.
5. **Taint cascade could never reach the auto-created procedures.** Screen/exam originally stamped "the visit's most recent *PASSED* load", so a later FAILED indicator could never taint them. Changed to "the unit's most recent load by `cycle_completed_at` DESC, `created_at` DESC tie-break, regardless of spore_result".
6. **`ERR_VARNISH_CAP_EXCEEDED` was arithmetically unhittable** — 4 applications each ≥90 days apart needs 360 days, longer than a school year. Lowered `VARNISH_MAX_APPLICATIONS_PER_PERIOD` from 4 to 2 (also the real Medicaid benefit), making the cap reachable in a 3-visit chain.
7. **Chair-minute ledger contradiction**: the TAINTED transition said minutes are *not* released while the ledger formula excluded TAINTED. Reconciled on the formula (recompute over `{PLANNED, PERFORMED}`).
8. **Unreachable enum values** removed rather than left dead: `Site.CLOSED`, `PortableUnit.RETIRED`, `Coverage.TERMINATED` (no producing endpoint existed).
9. **Gate-masking check**: rung 9 (period freeze), 10 (site hold), 15 (unit quarantine) and 4 (confidentiality wall) each verified to be conditionally scoped, never permanently masking a lower rung. The freeze carries an explicit `PERIOD_FREEZE_EXCLUDED_ENDPOINTS` list with a *why* per exclusion — notably reports/period-status (else CLOSED is unreachable and the freeze irreversible) and referral/follow-up (else rungs 33/34 die after a freeze).

Verified mechanically: all 36 error codes have a producing rung *and* appear in a test; all 38 rungs are cited by at least one design instance; every state in every machine is reachable from its initial state; 0 unreachable enum values; 0 unbound `${var}` placeholders; 0 unresolvable `grounds:` refs; 74 instance names all unique; all `excluded_because` stubs point at real §1.8 instances.

### Mutate-then-reject rungs (4, each with its already-terminal companion documented)
Unit-quarantine lazy sweep (15), consent expiry (24), referral attempt cap (34), coverage expiry (35). For each, the design states what happens when the row is *already* in the terminal state — three return the same error with no write and no version bump (distinguishable by version), and the referral cap is explicitly pre-empted by the rung-11 state gate into `ERR_INVALID_STATE`.

### Instance counts
- **§1.8**: 9 rule_ids, **23 instances** (3/3/3/2/3/3/2/2/2)
- **§1.9**: 9 sections, **51 instances** — 43 with full recipes + 8 `excluded_because` stubs

**ORCH-VERIFY-STEP2:** all three files `yaml.safe_load` clean; SCAFFOLD.yaml carries neither design key; counts confirmed directly (15 entities / 70 endpoints / 36 errors / 21 calculations / 38 validations); independent ALL_CAPS sweep → 235 tokens, all constant-shaped ones resolve to declared values (`PROCEDURE_CHAIR_MINUTES`, `PROCEDURE_FEE_SCHEDULE_CENTS`, `COMMERCIAL_ALLOWED_SCHEDULE_CENTS` are declared as value tables; residual tokens are enum members, error ids, or prose words). 0 undeclared confirmed.

## Step 4: Generate PRD — 2026-08-04T05:22:00.000Z

The PRD is complete and all three hard contracts pass.

### Deliverable
`workspace/PRD.md` — **592 lines, 19,188 words, 137 KB**.

### Section inventory
§1 Introduction (3 paras) · §2 Global Specs — 2.1 Personnel/Roles/Identity, 2.2 API Response Structure (verbatim), 2.3 Pagination/Ordering/Filter Semantics, 2.4 Identity/Timestamp Rendering/Version Ledger, 2.5 Logical Clock & Time Arithmetic, 2.6 The Thirty-Eight-Rung Validation Ladder, 2.7 The Four Gates and Their Deliberate Exclusions, 2.8 Lazy Sweeps and Mutate-then-Reject, 2.9 OCC on Parent Rows, 2.10 Money Precision + Four Conservation Identities, 2.11 Cascade Bookkeeping · §3 Business Logic — 3.1 Programme Year/Sites/Holds, 3.2 Roster & Two Consent Regimes, 3.3 Portable Equipment & Spore Cascade, 3.4 Staffing/Scheduling/Chair-Minute Ledger, 3.5 Chairside Encounter, 3.6 Eligibility/Sliding Fees/Three Pricing Regimes, 3.7 Plans/Referrals/Follow-Up, 3.8 Reporting/Disclosure/Freeze · §4 Endpoints (4 cols) · §5 Errors (2 cols).

### Coverage verification (machine-checked by the subagent)
- **70/70 endpoints** in §4, all role sets byte-match the scaffold (0 mismatches)
- **36/36 error codes**, all HTTP statuses match
- **38/38 rungs** rendered in strict priority order 1→38
- **21/21 calculations**, **13/13 SM axes (61 transitions)**, **3/3 OCC rules**, **4/4 invariants**
- **52 constants**, all values literally present; **111 enum/state values**, 0 missing
- §2.2 byte-identical to the canonical source

### Hard Contract Reports
```
Field coverage check:
- entities[].fields: 155 required, 155 present, 0 missing
- endpoints[].request_body: 96 required, 96 present, 0 missing
- endpoints[].query_params: 33 required, 33 present, 0 missing
- auxiliary identifiers (envelope, report payload keys, common fields): 34/34
Status: PASS

Rule coverage check:
- validations[] with priority: 38 checked, 38 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 61 checked, 61 fully expressed, 0 missing
- calculations[]: 21 checked, 21 fully expressed, 0 missing
- validations[] conditions: 38 checked, 38 matchable to error_id, 0 missing
- endpoints[].side_effects / applies_to: 70 checked, expressed, 0 missing
- entities[].fields[] structured content: 155 checked, reconstructible, 0 missing
- sibling-branch symmetry: 5 dual-variant calcs + PASSED/FAILED spore fork + 3 pricing regimes + 2 consent regimes + 2 overlap geometries = 13 groups, equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 1103
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- plain-text path leakage: 0
Status: PASS
```

### How the 9 emphases were handled
1. **38 rungs** — §2.6, one bold paragraph each, exact error id + HTTP status + exact endpoint scope. Gate rungs (9, 10, 15, 4) name their covered set *and* §2.7 enumerates every exclusion with its reason (e.g. site-hold gate deliberately excludes complete/cancel/screen/exam/price so lower rungs stay reachable).
2. **Enum routing** — rung 7 lists all 21 routing fields with their closed value sets, closing with "**No other field routes to this error.**" plus the contrast that list filters yield an empty page, not an enum error.
3. **Four mutate-then-reject rungs** — §2.8, each with (a) first-touch commit + version bump + error, and (b) explicit second-attempt behaviour: quarantine → same error, *no* write/bump; consent → same error, no write; referral cap → rung-11 `ERR_INVALID_STATE` pre-empt, no write; coverage → same error, no write. Rung-33 pre-emption of rung 34 also stated.
4. **Timestamps** — §2.4: uniform 3-fractional-digit `Z`, exhaustive field list, caller instants **re-rendered canonically** (truncating example given), separate `YYYY-MM-DD` family enumerated.
5. **Version granularity** — §2.4 states the one-bump-per-row-per-request rule plus two explicit non-bumping families (read-derived projections; cross-aggregate ledgers `booked_chair_minutes` / varnish counters). §2.11 is an exhaustive per-operation ledger for all 43 mutating operations, plus the global report-staling cascade riding on every period-gated write.
6. **List semantics** — §2.3: `created_at` ASC, tie-break by **insertion order** (explicitly *not* `id`), `limit` 10/1/100, `offset` 0, meta fields, off-enum & unknown-FK filters → empty page, only `limit`/`offset` range-checked.
7. **Dual-variant calcs** — all 5 render both branches with fork conditions, rounding order and precision: consent expiry, triage band, allowed amount, patient responsibility (per-line-round-then-sum stated as pinned), referral SLA. Sliding-fee bands stated inclusive-of-upper with all four boundary values called out; surcharge tiers likewise.
8. **Invariants & OCC** — §2.10 renders all 4 as enforceable prose with forward/compensating actions; §2.9 names field, request field, error, status and rung for each of the 3 OCC rules.
9. **Non-firing cascade legs** — spore cascade: link 3 skips non-`PRICED` encounters (and explicitly does *not* revert `CLAIMED`/`PAID`/`DENIED`), link 4 skips non-`ACTIVE` plans, link 5 skips already-answered referrals; consent downgrade: upgrade/no-change runs link 1 only, encounters retaining live procedures are not deferred, only `EXAMINED`/`TREATED` encounters move; report submit: `IN_PROGRESS`/`HOLD_BLOCKED`/terminal visits untouched.

### Un-prejudged friction points (carried forward to Steps 5/6/7)
1. **Off-by-one in scaffold cross-references.** State machines and calculations cite rung numbers from an earlier 37-rung table (e.g. "consent expiry at priority 23", "coverage sweep at 34", "supervision at 19", "overlap at 29/30"), while `validations:` itself numbers them 24, 35, 20, 30/31. Rendered the ladder from the `validations` table (authoritative and self-consistent); relative ordering unaffected, so no behaviour changes.
2. **`EXAMINED → DEFERRED` counting rule disagrees with itself.** Transition precondition says "zero procedures left in `PLANNED`/`PERFORMED` **other than the auto-created D0190/D0150 rows**"; the amend-tier cascade text says "zero `PLANNED`-or-`PERFORMED` procedures". The latter reading makes the leg unreachable. Rendered the state-machine reading (exclude auto-created rows).
3. **Coordinator report scoping is error-shaped but applied to a list.** Rung 5's `applies_to` includes `GET /reports` with `ERR_UNAUTHORIZED`, while that endpoint's own description says a SiteCoordinator sees only their own site's reports. Rendered: single-read → 403; list → result-set restriction after caller filters (empty page for another site).
4. **Undeclared error routing for four constraints with no error id in the scaffold.** Routed and stated explicitly: `Patient.patient_type` vs `Site.site_type` mismatch, duplicate `external_ref` within a site, duplicate `unit_code`, `Consent.site_id` ≠ patient's site, missing `member_id` on non-uninsured coverage, `verified_through_date` already past → `ERR_VALIDATION` (rung 6); reschedule cap/window, "no procedure still `PLANNED`" guards, consent-verify-past-expiry → `ERR_INVALID_STATE` (rung 11, explicitly declared as owning declared preconditions lacking their own error id).
5. **`TAINTED → VOIDED` would double-decrement the chair ledger** if applied incrementally. Resolved by rendering both the chair ledger and varnish counters as *full recomputations over surviving rows* — makes every compensating path idempotent.
6. **Two unreachable-by-construction rules rendered as guarantees, not tests:** rung 26 on screen/exam (D0190/D0150 both require rank-1 `SCREENING_ONLY`, the minimum tier), and the `CLAIMED` precondition that Medicaid `patient_responsibility_cents` be 0 (always true, since rung 37 refuses the only override path).
7. **UNINSURED allowed-amount ordering inversion.** `encounter_allowed_amount_cents` defines the uninsured branch as equal to `patient_responsibility_cents`, computed one step later. Rendered the pricing pass as six explicitly ordered steps with the uninsured allowed amount assigned in step six.

**ORCH-VERIFY-STEP4:** `workspace/PRD.md` present, 592 lines / 19,188 words; grep for `SCAFFOLD_DIFFICULTY|SCAFFOLD_CORNER|scaffold_difficulty|scaffold_corner` returns 0 hits (no design-index leakage); 5 top-level sections as reported.

## Step 5: Generate unit tests — 2026-08-04T05:55:00.000Z

Test infrastructure and suite generated for `task_0926_mobile_dentistry`.

### Files written
`test_helpers/` (9 files, ~2,000 lines) — `types.py` (34 status/role enums + 15 entity TypedDicts, all four common fields on every entity), `api_client.py` (70 endpoint methods + clock route), `api_errors.py` (36 error ids), `assertions.py` (`parse_instant`/`assert_same_instant`/`assert_same_date`/`add_business_days`, 15 per-entity assertions, `assert_money_split_closes`, `assert_chair_ledger_matches`), `constants.py`, `factories.py`, `test_users.py` (per-instance header builders for all four entity-backed roles), `fixtures.py` (499 lines, 5 tiers), `__init__.py`.
`test_suite/` — `conftest.py` + 10 test files (~3,300 lines).

### Coverage
- **Queue A (Difficulty): 23/23 instances translated, 0 skipped** — 46 tests, exactly 2 per instance.
- **Queue B (Corner): 43/43 non-stub instances translated, 0 skipped** — 43 tests, ≥1 each. All 8 `excluded_because:` stubs verified: every `difficulty_instance` cross-reference resolves to a real queue-A `name:`; no placeholder emitted.
- **`def test_` count = 89; `Design:` tag count = 89** (exactly one tag per test, every tag resolving to a real non-stub instance).
- **0** `skip`/`skipif`/`xfail`/`pytest.skip` markers anywhere.
- 89 tests collect cleanly under pytest; pyflakes reports no undefined or unused names outside the barrel export.

### Instant-comparison audit
- **30** instant-valued assertions, all routed through `assert_same_instant` (millisecond-resolution semantic compare); **9** date-valued assertions through `assert_same_date`.
- **0 raw string equalities on instant- or date-valued fields.** The one field-to-field inequality check (school vs SNF `expires_at`) compares parsed instants, not renderings.
- No `scaffold`/`§1.x`/`Table N` references leak into generated comments or docstrings.

### PRD adjudication notes
All seven declared friction points were re-derived from PRD prose rather than pre-judged; each affected instance survived the two-condition filter. The two unreachable rules (rung 26 on screen/exam, the Medicaid-zero CLAIMED precondition) are targeted by no instance, so nothing needed skipping.

**One input deviation, not a skip** — `Corner/validations/manual_patient_share_on_a_medicaid_encounter_returns_balance_bill_error`: the recipe's `manual_patient_responsibility_cents: 500` is **not uniquely derivable**. Rung 6 bounds that field by the encounter's `total_charge_cents`, which on a not-yet-priced encounter is `0`; a ladder-strict reader returns `ERR_VALIDATION`, a reader who computes the total first returns `ERR_MEDICAID_BALANCE_BILL`. The test instead supplies `0`, in range under **both** readings, so rung 37 is the only rung that can fire. A comment in the test records why.

**Assertions dropped for silence-pattern reasons** (instance still generated):
- `Site.facility_contact_name == null` — PRD names the field as optional but never states the server-side default (default-value pattern).
- `Encounter.exam_modality == null` after a refused teledentistry exam — PRD's initial-state sentence covers "every screening finding", not `exam_modality`; the test asserts `clinical_status == SCREENED` and zero auto-created `D0150` rows instead, both explicit.

No other PRD gaps encountered.

## Step 6: Generate implementation — 2026-08-04T05:52:00.000Z

Implementation complete at `workspace/implementation/`.

### Module inventory — 24 files, 4,641 lines
| Layer | Files (lines) |
|---|---|
| Foundation | `constants.py` 240, `timefmt.py` 143, `clock.py` 30, `errors.py` 88, `store.py` 83, `envelope.py` 53, `validation.py` 280 |
| Domain logic | `calc.py` 491, `cascades.py` 281, `gates.py` 144, `serializers.py` 294 |
| Routes | `periods.py` 90, `sites.py` 147, `roster.py` 329, `equipment.py` 243, `visits.py` 286, `encounters.py` 406, `procedures.py` 229, `plans.py` 289, `coverage.py` 99, `reports.py` 292 |
| Entry/launcher | `app.py` 76, `start.sh` 26, `requirements.txt` 1 |

Built incrementally across ~25 bounded writes; no single large write.

### Endpoint completeness gate
**scaffold endpoints 70 / registered routes 70 / MISSING 0 / EXTRA 0** — enumerated programmatically from `SCAFFOLD.yaml:endpoints[]`, diffed against an in-process `app.url_map` dump with `{id}`/`<id>` normalized.

### The two recurring bugs — adjudicated
**1. Timestamp rendering.** Single rule, no exceptions: every instant is parsed by `timefmt.parse_instant` (truncated to millisecond) and emitted by `timefmt.render_instant` as `YYYY-MM-DDTHH:MM:SS.mmmZ`. Caller instants are re-rendered, never echoed (`...T14:00:00Z` → `...T14:00:00.000Z`; `.123456Z` → `.123Z`). Every server-written instant — including `created_at`, `updated_at`, derived instants, and the envelope's `api_request_timestamp` — comes from the **logical clock**, never the wall clock. Verified structurally: `isoformat`/`strftime` appear nowhere outside `timefmt.py` (one inbound parse), and `datetime.now`/`utcnow`/`time.time` appear nowhere in the codebase.

**2. Enum routing.** Strict iff-rule. `check_enum` (the only path to `ERR_INVALID_ENUM`) is wired to **exactly the 21 PRD-listed request fields** across 23 call sites — `supervision_level` and `credential_status` each appear on both staff create and PATCH. Rung 6 does presence/JSON-type checking for those fields; every other enum-membership failure (patient_type↔site, regime↔site, payer_type-driven `member_id`, list filters) takes `ERR_VALIDATION` or an empty page.

### Storage
In-memory Python dicts only (`store.py`, 15 collections). No SQLite, no disk, no `/tmp`. Verified: fresh import → 15 collections, 0 rows; two consecutive `start.sh` boots each reported `total_count=0` after the previous boot created a site.

### The 7 friction points
1. **Rung numbering** — the PRD's 38-rung ordering is authoritative throughout; the scaffold's stale internal cross-references were ignored.
2. **`EXAMINED → DEFERRED`** — auto-created screen/exam rows carry an internal `_auto_created` flag; the deferral leg fires only when zero `PLANNED`/`PERFORMED` rows remain *excluding* those.
3. **Coordinator report scoping** — single read → `ERR_UNAUTHORIZED` 403; list → result-set narrowing to `site_id == X-User-ID` (another site yields an empty page).
4. **Error-less constraints** — reschedule cap, reschedule 30-day window, "no procedure still PLANNED" on complete/close, and consent-verify expiry all → `ERR_INVALID_STATE`; patient/site and plan/patient mismatches → `ERR_VALIDATION`.
5. **Ledgers** — `booked_chair_minutes` and `active_hold_count` are derived fresh; varnish counters are full recomputations over surviving rows scoped to the working period. No incremental deltas anywhere.
6. **Unreachable rules** — rung 26 on screen/exam and the Medicaid-zero-responsibility claim precondition are both implemented as stated; neither can fire.
7. **UNINSURED allowed amount** — assigned in step six, after `patient_responsibility_cents` exists; a manual override sets `allowed = override` for UNINSURED and leaves step four's allowed intact for COMMERCIAL.

**Reachability notes:** two rungs would have been shadowed by a literal rung-11 reading, so rung 11 defers precisely those cases — a `QUARANTINED` unit falls to rung 15 (only `IN_SERVICE` answers `ERR_INVALID_STATE` at 11), and a `STALE` report falls to rung 38.

### Boot verification
`start.sh` (executable, `$PORT`, `0.0.0.0`, `exec`, guarded pip install, `find_spec` import probe with retry) boots in under 3s. Three smoke suites run against one fresh server, all green, zero tracebacks. Conservation identities checked to the cent under all three regimes.

**ORCH-VERIFY-STEPS-5-6:** `def test_` 89 == `Design:` tags 89; `pytest.mark` occurrences 0; skip/xfail/skipif 0. **Isolation note — Step 6 finished ~155 s BEFORE Step 5**, so `implementation/` was on disk during test-gen's final stretch (reverse of the usual direction). Containment check: grep of `test_suite/`+`test_helpers/` for `implementation/|from app|import app|store.py|serializers.py|cascades.py|timefmt` → **0 hits**, no breach. Independent route diff (orchestrator-run, scaffold `endpoints[]` vs in-process `app.url_map`, path params normalized) → **70 scaffold / 70 registered / 0 MISSING / 0 EXTRA**. Impl persistence grep (`sqlite|json.dump|pickle|/tmp|open(`) → empty; wall-clock grep (`datetime.now|utcnow|time.time()`) → empty.

**Sweep pre-staged:** `workspace/sweep.sh` written as **4 waves of 2** (2 co-tenant `prd-bench-local-run` processes active at launch, load 2.7/8), ending with `touch implementation/SWEEP_DONE`; no inline `pkill`.

## Step 7: Run tests and iterate — 2026-08-04T06:12:00.000Z

**Clean pass on the first sweep — no iterations needed.** All 8 rounds: 89/89 passed, 0 failed, 0 errors, 0 skipped.

**Iterations run:** 1 (a single 8-round stability sweep, run as 4 waves of 2; ~4 min wall clock). No flakiness surfaced — the union of failing tests across all 8 rounds is empty, so no diagnostic protocol steps were triggered.

**Tests deleted:** none. **Fixes applied to `test_helpers/`:** none. **Fixes applied to `test_suite/`:** none. **Fixes applied to `implementation/`:** none.

### Isolation-audit result (negative, as hoped)
Steps 5 and 6 overlapped on disk, so the suite was swept for assertions encoding impl-only detail that PRD under-determines:
1. **Raw timestamp string equality — zero.** All 25 instant assertions go through `assertions.py::assert_same_instant` (parses both sides, millisecond resolution); dates via `assert_same_date`. Nothing compares rendered strings, so no test pins the implementation's `.000Z` formatter rather than PRD §2.4's rule.
2. **List-ordering / positional assertions — three, all determinate.** The only `rows[0][...]` chain (`test_02:376-378`) is guarded by `assert len(rows) == 1`. The genuine ordering assertions trace to verbatim PRD: roster `lines` ordered by patient `created_at` ascending (§3.8) and sliding-fee lines in `created_at` ascending order (§3.6).
3. **Exact `version` counter values — 16 sites, all PRD-derivable.** §2.11 is an exhaustive per-operation version ledger and §2.4 pins creation at 1, so each assertion quotes a named clause rather than observing the implementation.
4. **Response-field projections — clean.** Every `["field"]`/`.get("field")` token asserted across all 10 test files appears verbatim in the PRD. Non-PRD tokens are fixture dict keys only. The single exact-key-set assertion (`test_09:67`) is PRD-verbatim (§3.8: the three clinical keys are "omitted from the object entirely rather than present with null values").
5. **Bonus:** no assertions on `message` text, none on `api_request_id`/`api_request_timestamp` internals, no skip/xfail. The two free-text echo assertions are PRD-covered.

### Notes on the seven friction points
None produced a test/implementation disagreement — the suite's assertions on all seven are consistent with the PRD reading, including the four mutate-then-reject rungs (`test_05:484-493` consent-expiry first/second touch, `test_03:238-242` incubation sweep, `test_08:192,218` referral cap vs `ERR_REFERRAL_NOT_DUE` pre-emption, `test_07:537`/`test_10:205` coverage-expiry) and the coordinator report scoping split.

### Final per-round pass counts
| Round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| Passed | 89/89 | 89/89 | 89/89 | 89/89 | 89/89 | 89/89 | 89/89 | 89/89 |

**ORCH-VERIFY-STEP7 (a clean first sweep is verified, never accepted — it looks identical to a false-clean):**
- All 8 `results.N.json` re-parsed independently → **89 individual rows each** (not just an aggregate counter), status distribution `{'passed': 89}` every round, sorted test-name lists **byte-identical to round 1 in all 8**.
- `def test_` 89 == `Design:` tags 89 (post-sweep, matching the runner's collected count of 89).
- `pytest.mark` / `pytest.skip` occurrences: **0**.
- `find implementation/ test_suite/ test_helpers/ -newer results.1.json` → **empty**, so the 89/89 ×8 result describes the shipped tree; nothing was touched after the sweep.
- Impl grep for `sqlite|json.dump|pickle|/tmp|shelve|datetime.now|utcnow|time.time()` → **0 hits** (in-memory only, logical clock only).
- Each `round.N.log` contains `Killed` exactly once (the runner SIGKILLing the pre-boot server as per-test isolation swaps in a fresh one for test #1 — expected, not a crash) and **0** restart/boot-timeout/traceback lines.

## Step 8: Finalize PRD — SKIPPED — 2026-08-04T06:14:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with **0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes** — zero iterations beyond the baseline. `PRD.md` already determined every behavior the implementation exhibits at every site the suite exercised, so there is no `<step_7_diff>` to patch from. No subagent spawned; `PRD_FINALIZED.md` is intentionally absent. Step 9 therefore starts from `PRD.md` and is the only completeness pass.

## Step 9: Complete PRD — 2026-08-04T06:31:00.000Z

`workspace/PRD_COMPLETED.md` is written.

### Size
| | PRD.md | PRD_COMPLETED.md | Δ |
|---|---|---|---|
| lines | 592 | 594 | +2 |
| words | 19,188 | 21,293 | +2,105 |
| chars | 137,916 | 152,099 | **+14,183** |

41 hunks: 40 in-paragraph revisions, 1 new paragraph (the §2.3 filter roster). No new sections. **32 ambiguity-pins, 9 mismatch-revisions.**

### Changes
- **§2.2** — revise — ambiguity — `api_request_timestamp` is read from the **logical clock**, not host time — `envelope.py:28`
- **§2.3** — insert — ambiguity — per-endpoint filter-key roster for all 12 list endpoints; unrecognised query params silently ignored; empty filter value = absent; exact string equality — `validation.py:239`
- **§2.4** — revise — ambiguity — `created_at`/`updated_at` stamped from the logical clock — `store.py:46`
- **§2.4** — revise — ambiguity — sub-ms **truncated not rounded**; non-UTC offsets converted; naive instants read as UTC — `timefmt.py:33`
- **§2.4** — revise — ambiguity — `Site.active_hold_count` and `Encounter.tainted_procedure_count` are read-derived row counts — `serializers.py:32,181`
- **§2.6 r3** — revise — ambiguity — an absent/null/non-string body FK is not a rung-3 failure; falls to rung 6 — `validation.py:60`
- **§2.6 r5** — revise — ambiguity — coordinator narrowing precedes the page cut, so `total_count` counts only their own — `reports.py:216`
- **§2.6 r6** — revise — **mismatch** — the manual-override ceiling is the *about-to-be-computed* total, not the stored `total_charge_cents` (still 0 pre-pricing) — `encounters.py:311`
- **§2.6 r6** — revise — ambiguity — `cavitated_lesion_count`/`medical_complexity_count` have no range; negatives accepted — `encounters.py:171,177`
- **§2.6 r11** — revise — ambiguity — 5 extra rung-11 guards (PENDING consent on **screen/exam only**, unit `IN_SERVICE` on start, non-`PENDING` load, already-`VERIFIED` coverage, `SUBMITTED` report) + the 4 writes with **no** state precondition — `encounters.py:189`, `visits.py:193`, `equipment.py:147`, `coverage.py:81`, `reports.py:251`
- **§2.11** — revise — **mismatch** — completing a visit bumps `PortableUnit.version` **only** when it returns from `IN_SERVICE` — `visits.py:243`
- **§2.11** — revise — ambiguity — staff `PATCH` bumps version even when nothing changed; extra fields ignored; explicit null clears — `equipment.py:234`
- **§2.11** — revise — ambiguity — stale ripple uses only the written entity's own period (cross-period cascades excluded); revoke/amend/submit stale nothing — `gates.py:128`
- **§3.1** — revise — ambiguity — `SUBMITTED → REPORTING` leaves `state_submission_ref` intact — `periods.py:86`
- **§3.1** — revise — **mismatch** — `facility_contact_name` is read by nothing and appears in no payload; `active_hold_count` derived — `reports.py:132`
- **§3.2** — revise — ambiguity — SCHOOL expiry renders exactly `...T23:59:59.000Z` — `timefmt.py:119`
- **§3.2** — revise — ambiguity — revocation stamps `void_reason` = `CONSENT_TIER_DOWNGRADE`, `revoke_reason` optional, one link only, `invalidated_procedure_count` stays 0 — `cascades.py:190`
- **§3.2** — revise — **mismatch** — the expiry precondition guards the `PENDING_VERIFICATION` leg **only**; the SNF reaffirmation self-loop has none — `roster.py:226`
- **§3.3** — revise — ambiguity — never-calibrated unit reads a null `calibration_due_on` — `calc.py:113`
- **§3.3** — revise — ambiguity — `last_varnish_date` recomputes to the **latest** surviving `performed_at` date — `calc.py:169`
- **§3.3** — revise — ambiguity — an already-`QUARANTINED` unit is re-stamped and re-incremented on a further failure — `cascades.py:114`
- **§3.4** — revise — ambiguity — capacity discards sub-minute remainder first — `calc.py:128`
- **§3.4** — revise — ambiguity — reschedule window is an **absolute** 30 days, inclusive; nothing else re-checked (capacity may fall below booked) — `visits.py:151`
- **§3.4** — revise — ambiguity — start: visit-status then unit-`IN_SERVICE` are both `ERR_INVALID_STATE`, above the quarantine/calibration gates — `visits.py:189`
- **§3.4** — revise — **mismatch** — complete returns the unit out of `IN_SERVICE` only; a mid-visit quarantine is left untouched — `visits.py:242`
- **§3.5** — revise — ambiguity — registration has **no** visit-state precondition — `encounters.py:82`
- **§3.5** — revise — ambiguity — an `ONSITE` exam ignores and never stores `teledentistry_reviewed_at` — `encounters.py:268`
- **§3.5** — revise — ambiguity — planning has no parent-state precondition; `treatment_plan_id` checked only for existence; tooth/surface inert for non-`D1351` — `procedures.py:57`
- **§3.5** — revise — ambiguity — perform's `sterilization_load_id` needn't belong to the visit's unit; encounter charge fields untouched until pricing — `procedures.py:143`
- **§3.5** — revise — ambiguity — void: reason optional, no state gate, `taint_reason` **not** cleared — `procedures.py:209`
- **§3.6** — revise — **mismatch** — `payer_name` on an `UNINSURED` coverage is stored, not prohibited — `coverage.py:27`
- **§3.6** — revise — ambiguity — re-verifying an already-`VERIFIED` coverage is `ERR_INVALID_STATE` — `coverage.py:81`
- **§3.6** — revise — ambiguity — a commercial manual override may drive `plan_paid_cents` **negative**, unclamped — `calc.py:284`
- **§3.6** — revise — ambiguity — `denial_reason` optional and touched by the `DENIED` leg only; claim clears it on both legs; Medicaid zero-share check guards `PRICED → CLAIMED` only — `encounters.py:366`
- **§3.7** — revise — **mismatch** — a plan may be created from an unscreened encounter; a null `urgency_band` falls through to the `NO_OBVIOUS_PROBLEM` branch everywhere — `plans.py:61`, `calc.py:329`
- **§3.7** — revise — **mismatch** — a replacement `dental_home_name` overwrites on **any** send, not just from `DECLINED` — `plans.py:246`
- **§3.8** — revise — **mismatch** — a `PROGRAM_PERIOD` report *requires* none of the three but stores them if supplied — `reports.py:174`
- **§3.8** — revise — ambiguity — roster/parent line derivation: `triage_band` = last banded encounter, `procedure_codes_performed` in `created_at` order with repeats, `follow_up_due_date` from the last plan — `reports.py:51`
- **§3.8** — revise — ambiguity — PARENT `patient_responsibility_cents` sums **all** in-period encounters regardless of `billing_status` — `reports.py:150`
- **§3.8** — revise — ambiguity — the report-type and period-state guards on rung 11 pre-empt rung 38 — `reports.py:276`
- **§4** — revise — ambiguity — `amend-tier` is the one action endpoint answering **201** — `roster.py:329`
- **§4** — revise — **mismatch** — treatment-plan create row no longer claims "from an examined encounter" — `plans.py:36`

### Areas checked and found genuinely clean (negative signal — PRD-generator habits that are working)
- **All 70 §4 role sets** match `authenticate()` exactly, endpoint for endpoint. Zero drift.
- **All 36 error→HTTP-status pairs** in §5 match `errors.py` exactly.
- **The rung-7 closed enum list** — all 21 named fields route to `ERR_INVALID_ENUM` and nothing else does.
- **The 19 period-gated writes** in §2.7 match `PERIOD_GATED_ENDPOINTS`, and all 19 (and only those 19) fire the stale ripple; the site-hold gate's 4 endpoints and the quarantine gate's 2 are exact.
- **Every boundary inclusivity** — sliding-fee bands, surcharge tiers, Medicaid cap, coinsurance rounding, per-line-then-sum, the 2,500 floor and band `E`'s exemption, unit (strict, +90 min) vs staff (non-strict, no buffer) overlap geometry, calibration `DUE`/`EXPIRED`, teledentistry closed 72 h, varnish 90/2, chair-capacity equality, consent/coverage expiry senses, referral 21-day and cap-3, follow-up 14-day grace, spore 14-day cutoff (strictly-after / at-or-before).
- **The §2.11 version ledger** — 29 of 31 entries verified correct; only the two flagged above were wrong.
- **The depth-5 spore cascade** and the 3-link downgrade cascade including every stated non-firing leg.
- **Both triage rule sets**, the supervision matrix and its three-step presence rule keyed on the *required* level.
- **§2.4 timestamp rendering** — `render_instant` is genuinely uniform across every field named, and every date field renders bare.

**ORCH-VERIFY-STEP9:** `PRD_COMPLETED.md` present (594 lines / 21,293 words / 152,099 chars vs PRD.md 592 / 19,188 / 137,916 — +14,183 chars); `PRD_FINALIZED.md` correctly absent (Step 8 skipped); `find workspace/implementation test_suite test_helpers -newer results.1.json` → **empty**, so Step 9 touched only the PRD and the shipped 89/89 ×8 tree is unchanged.

---

# PIPELINE COMPLETE — task_0926_mobile_dentistry

**89/89 tests passing on all 8 stability-sweep rounds, zero Step-7 deletions and zero fixes of any kind.** Step 8 skipped (clean first sweep); Step 9 did the whole completeness job (32 ambiguity-pins + 9 mismatch-revisions).
