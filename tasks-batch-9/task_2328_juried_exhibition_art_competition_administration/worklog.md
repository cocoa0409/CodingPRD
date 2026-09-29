# Worklog — task_2328_juried_exhibition_art_competition_administration

## Step 1: Create Task Directory — 2026-09-01T17:22:00.000Z

Created `tasks/task_2328_juried_exhibition_art_competition_administration/` and `workspace/` subdirectory (directory name pre-allocated by orchestrator invocation; no index scan performed).

## Step 2: Generate Scaffold — 2026-09-01T19:11:00.000Z

All three scaffold artifacts are complete and lint-clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2328_juried_exhibition_art_competition_administration/`)
- `SCAFFOLD.yaml` — 139,658 B; top-level keys exactly `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` (no difficulty/corner keys).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 187,793 B; single key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 381,063 B; single key `scaffold_corner_design`.

**SCAFFOLD.yaml counts**: 15 entities, 8 state machines across Entry/Artwork/JuryRound/JurorAssignment/Award/Sale plus the Exhibition status and settlement axes, 5 OCC concurrency rules, 68 endpoints (incl. the mandatory `POST /_clock/set_current_utc`), 66 error codes, 6 roles (CallManager, JuryChair, Juror, Artist, Registrar, FinanceOfficer) with segregation of duties on award propose/confirm and sale record/payout. `complexity_profile`: archetype `multi_party_negotiation` + `ledger_reconciliation`, layers `[dual_variant_calculation, cascading_side_effects, optimistic_concurrency, selector_policy]`, `state_machine_shape: parallel` (secondary cyclic/branching/compound), `role_model: segregation_of_duties`, `consistency_model: immediate`, `difficulty_level: expert_plus`.

**§1.8 difficulty coverage**: all 9 mandated rules, 21 instances (≥2 each) — dual_variant_calc (2), combinatorial_formula (3), non_linear_state_machine (3), transitive_cascade (2), priority_pair_validation_conflict (3), boundary_precision_check (2), cross_entity_state_dependency (2), resource_temporal_overlap (2), compensating_invariant (2).

**§1.9 corner coverage**: 89 instances across all 9 sections — entities 12, state_machines 19, calculations 10, validations 8, endpoints 6, errors 21, rbac 5, cross_cutting_layers 7, consistency_model 1. 65 are full `test_recipe`s; 24 are `excluded_because` stubs citing the §1.8 instance that already probes that claim. One OCC stale-version recipe exists per §1.2.1 rule (assignment-create, installation-plan, award-confirm, promotion, payout-release). Every one of the 66 §1.6 error codes is triggerable somewhere in §1.8+§1.9 (verified programmatically; the last gap, `ERR_ENTRY_NOT_FOUND`, was closed by adding a `GET /entries/{unknown}` probe).

**Lint** (`skills/prd-bench-scaffold-generator/scaffold_lint.py`):
```
Coverage
  §1.5 endpoints declared:    68
  §1.1 entities declared:     15
  §1.8 instances scanned:     21
  §1.9 instances scanned:     65
  Calls scanned (§1.8+§1.9):  1933

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Notes for later reuse: the corner file is large enough that `yaml.safe_load` (pure Python) exceeds a 120 s timeout — use `yaml.load(..., Loader=yaml.CSafeLoader)` (~1 s). No sibling task directory was read at any point, per the hard constraint.

## Step 3: Copy Shared Files — 2026-09-01T19:12:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 B).

## Step 4: Generate PRD — 2026-09-01T19:40:00.000Z

PRD written and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2328_juried_exhibition_art_competition_administration/workspace/PRD.md` — 493 lines, ends at §5 with no audit footer.

**Structure (5 H2, 20 H3):**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications — 10 subsections: 2.1 Council Roles and Access Control · 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Common Resource Properties · 2.5 Identifier Resolution and Exhibition Scope Coherence · 2.6 The Logical Clock and the Calendar of a Call · 2.7 Optimistic Concurrency on Contested Parents · 2.8 Cents, Rounding and the Order of Arithmetic · 2.9 Segregation of Duties · 2.10 Order of Validation (full 50-rung precedence ladder)
- §3 Business Logic — 10 lifecycle subsections: standing up a call · artists/entries/works · fee assessment, submission, waiver, withdrawal + deadline sweep · convening the jury (conflicts, sessions, honorarium proration) · scoring (composite, provisional vs quorum-certified, round cycling) · acceptance list + waitlist · delivery, condition, insurance, wall planning, installation · sponsors and awards · sales, tax, commission, payout · closing, returns, forfeiture, settlement
- §4 Endpoint Definitions — 68 rows, 4 columns
- §5 Error Code Catalogue — 66 rows, 2 columns

**Hard Contract 1 — Field coverage check:**
- `entities[].fields`: 188 required, 188 present, 0 missing
- `endpoints[].request_body` / `input` (query params are folded into `input` in this scaffold): 113 required, 113 present, 0 missing
- `endpoints[].query_params` / `path_params`: 0 declared separately, 0 missing
- Status: **PASS**

**Hard Contract 2 — Rule coverage check:**
- `validations[]` with priority: 50 checked (priorities 1–50), 50 expressed in prose as an explicit ordered ladder in §2.10 with error ID, HTTP status and endpoint scope, 0 missing
- `concurrency_rules[]` OCC rejections: 5 declared + 1 implied by validation priority 50 (`/exhibitions/{id}/acceptance-list`) = 6 checked, 6 expressed (operation + `expected_…_version` + `ERR_STALE_VERSION`/412 all named, each with its contention story), 0 missing
- `state_machines[].transitions`: 10 machine blocks / 45 transitions checked, 45 fully expressed, 0 missing; all state names present
- `calculations[]`: 10 checked, 10 fully expressed with pinned evaluation order and every constant (120.0/2000, 8.00, 0.10, 350/275/190/25000, 0.40, 50000/150000, 1500/0.5/30, tier floors), 0 missing
- `validations[]` conditions: 50 checked, all matchable to error_id in prose; all 66 error IDs appear in prose outside §5, 0 missing
- `endpoints[].side_effects` / `applies_to`: 68 endpoints' side effects and every `applies_to` scope expressed, 0 missing
- `entities[].fields[]` structured content: 188 checked — all 29 declared defaults, all computed-field definitions (incl. the broad `accepted_count` state set, `valid_score_count` round-1 scoping, `blind_label` format) reconstructible from prose, 0 missing
- Sibling-branch symmetry: 6 groups checked (accept/waitlist/decline; shortlist/decline fork; gallery vs purchase-award split with parallel worked numbers; fee payment vs waiver; void→`ON_VIEW` vs →`RETURN_PENDING`; expertise match vs cap) — equal prose density, 0 asymmetric
- Status: **PASS**

**Hard Contract 3 — Path purity check (§3 only):**
- backtick tokens scanned: 927
- tokens starting with `/`: 0 · tokens containing `/`: 0 · bare HTTP-method tokens: 0 · method+path combined tokens: 0 · raw unbackticked path-like strings: 0
- Status: **PASS**

**Cross-checks against the scaffold:** all 68 method+path pairs present with zero extras; role lists match the scaffold exactly on all 68 rows (0 mismatches); all 66 error rows present with matching HTTP statuses and no extras; the §4 preamble's "201 on create, 200 otherwise" matches the scaffold's codes exactly (the 15 `201` endpoints are precisely the resource-creating ones).

Both withheld design files were never opened, grepped or referenced.

## Step 5: Generate Unit Tests — 2026-09-02T00:35:00.000Z

Generation and verification are complete.

## Files written

`test_helpers/` (9 modules, Stage 1)
`/home/ubuntu/github/CodingPRD/tasks/task_2328_juried_exhibition_art_competition_administration/test_helpers/` — `__init__.py`, `constants.py`, `types.py`, `api_errors.py`, `test_users.py`, `api_client.py`, `factories.py`, `fixtures.py`, `assertions.py`

`test_suite/` (conftest + 18 test modules, Stage 2)
- Queue A (difficulty): `test_01_entry_fee_and_image_standard.py`, `test_02_score_means_and_expertise_cap.py`, `test_03_round_cycle_conflicts_and_scope.py`, `test_04_acceptance_fork_and_promotion.py`, `test_05_wall_planning_and_deinstall.py`, `test_06_sale_split_and_purchase_award.py`, `test_07_award_budget_void_and_payout.py`, `test_08_settlement_ledger_and_two_axes.py`, `test_09_juror_sessions_and_honorarium.py`
- Queue B (corner): `test_10_entity_shapes_and_references.py`, `test_11_lifecycle_transitions_and_cascades.py`, `test_12_derived_money_and_counts.py`, `test_13_validation_ladder_and_boundaries.py`, `test_14_endpoint_surfaces.py`, `test_15_error_catalogue.py`, `test_16_role_boundaries_and_ownership.py`, `test_17_optimistic_concurrency.py`, `test_18_immediate_visibility.py`

## Test counts

| | instances | tests |
|---|---|---|
| Queue A (§1.8) | 21 / 21 non-stub covered | 51 |
| Queue B (§1.9) | 64 / 65 non-stub covered | 64 |
| **Total** | | **115** |

Queue B per section: entities 11/12, state_machines 13/13, calculations 6/6, validations 6/6, endpoints 6/6, errors 11/11, rbac 5/5, cross_cutting_layers 5/5, consistency_model 1/1. The 24 corner stubs and 0 difficulty stubs carrying `excluded_because:` were never translated.

## Coverage audit (machine-checked)

- `pytest --collect-only`: **115 collected**, no import errors; `compileall` clean.
- Design tags: 115 tests, 115 `Design:` lines — exactly one per docstring, always the last line, every tag resolves to a real non-stub instance name; zero unknown, dual, stub or missing tags.
- Queue A depth: every one of the 21 instances has **≥2** tests (min 2, none at 1).
- PRD citations: 205 quoted strings ≥25 chars extracted by AST; **all 205** survive a whitespace-normalized literal substring match against `workspace/PRD.md` (missing=0). A separate full-sentence (C3) sweep flagged 12 quotes; 6 were paragraph-opening sentences directly after a `### x.y.` heading (legitimate), and the remaining 5 were colon-introduced clauses that I expanded to include their lead-in clause this pass (`test_01`, `test_02` ×2, `test_06`, `test_09`).
- No occurrence of the word "scaffold" anywhere in `test_suite/` or `test_helpers/`.

## Instances skipped (1)

- `Corner/entities/artwork_status_and_placement_client_input_ignored` — the instance asserts that a client-supplied `status`/`placement_status` on artwork creation is silently ignored and the create still succeeds. The PRD never states that unknown or system-owned keys are ignored rather than rejected (§2.10 rung 6 only constrains declared fields), so the asserted 201-with-defaults outcome is not uniquely derivable. Left as a gap; no weakened test, no xfail, no placeholder.

## Design-index vs PRD conflicts resolved in favour of the PRD

`INSTRUCTOR` → `TEACHER_STUDENT` conflict relation; `HONORABLE_MENTION` → `JURORS_CHOICE` (not in the PRD enum); DRAFT `entry_fee_cents == 0` rather than null; `ERR_ACCEPTANCE_CAPACITY_REACHED` is 409 not 422; sale terminal state `PAYOUT_RELEASED` not `PAID_OUT`; non-eligible-artist refusal lands on `POST /entries`; and the rbac ownership instance's foreign `GET /entries/{id}` hop was replaced with the PRD-explicit foreign `GET /artists/{id}` (§2.1's ownership enumeration does not cover reading an entry). Four individual assertions whose text the PRD does not support were dropped from otherwise-valid tests (test_08 `council_retention_cents`, test_12 round `version == 4`, test_15 `ERR_ARTIST_PAYOUT_HOLD` hop, test_16 foreign entry read).

Nothing was read or written under `workspace/implementation/`; no test has been executed against a live server (collection and static citation analysis only).

## Step 6: Generate Implementation — 2026-09-01T23:55:00.000Z

Implementation complete and verified.

## Files

All under `/home/ubuntu/github/CodingPRD/tasks/task_2328_juried_exhibition_art_competition_administration/workspace/implementation/`:

| File | Lines | Role |
|---|---|---|
| `core.py` | 1161 | Store, envelope/meta, versioning + dirty-set flush, logical clock, auth, validators, all 10 calculations, all recompute cascades |
| `routes_jury.py` | 552 | Jurors, conflict declarations, rounds, sessions, scores |
| `routes_exhibitions.py` | 514 | Clock, exhibitions, phase advance, acceptance list, settlement, sweep, wall segments |
| `routes_finance.py` | 418 | Sponsors, awards, sales ledger |
| `routes_artworks.py` | 402 | Artworks, images, condition reports, promotion, wall planning, install/deinstall, returns |
| `routes_entries.py` | 389 | Artists, entries, artwork attachment, submit/fee/waiver/withdraw |
| `errors.py` | 93 | 66 catalogue error IDs → HTTP status, `ApiError` |
| `app.py` | 59 | App factory, blueprint registration, error handlers |
| `start.sh` | 11 | Launcher (conditional pip install, `exec python3 app.py`, honors `$PORT`) |
| `requirements.txt` | 1 | `Flask>=2.2` |

**3600 lines total. 68 endpoints registered**, matching the 68 in PRD §4 exactly. Storage is pure in-memory dicts; no seeding, no disk artifacts (`__pycache__` removed, no stray `routes/` dir).

## Boot verification

Fresh process on port 18328 booted clean and returned an empty store on every collection (`total_count: 0`), correct envelope/meta shape, 401 on missing auth, and the logical clock echoing `2026-08-05T00:00:00Z`. Server killed; port free.

## Behavioural verification

Four end-to-end scenarios were run against live servers, each on a freshly booted empty store. Numeric results reproduce the PRD's worked examples exactly:

- **Entry fee** 6951 (3713 + 1238 + 2000 oversize, per-line rounding); **composite** 9.0 and non-expert cap 8.0; **gallery split** 229885/20115/80460/149425/250000; **purchase-award split** 250000/21875/25000/225000/271875
- **Honorarium proration** 16667/16667/16666 across 3 equal sessions, re-prorating to 25000/25000/0 on cancel; retroactive conflict voiding 1 score and reopening the quorum shortfall
- **Wall geometry** conserved (`occupied + available == length`) through plan/install/deinstall/close; 15 cm buffer exact (gap 14 rejected, gap 15 accepted)
- **Storage accrual** 1500/day with the floor(declared/2) cap (a 2000-cent work capped at 1000); forfeiture at overdue day 31, two forfeits setting `payout_hold`; COURIER returns correctly excluded from the sweep
- **Settlement** gross 470000 / tax 29770 / commission 154081 / payable 286149 / retention 135331 (= 154081 − round_half_up(25000 × 0.75), tier keyed on commission); all 8 sponsor tier boundaries correct
- ~60 distinct error paths exercised across the precedence ladder, each returning the expected error ID and status (e.g. 402 `ERR_AWARD_BUDGET_EXCEEDED`, 409 `ERR_QUORUM_NOT_MET`, 409 `ERR_ROUND_REOPEN_LIMIT`, 412 `ERR_STALE_VERSION`, 422 `ERR_WALL_WEIGHT_EXCEEDED`, 403 `ERR_SEGREGATION_OF_DUTIES`)

## One bug found and fixed

`POST /artworks/{id}/condition-reports` rejected a second `INTAKE` report because the work was already `DELIVERED`. PRD §3.7 explicitly allows re-inspection ("a re-inspection supersedes an earlier one"), so the guard now admits `ACCEPTED` or `DELIVERED` and only drives the `ACCEPTED → DELIVERED` transition on first intake. Re-verified: grade correctly supersedes.

Two other apparent failures were traced to my test expectations, not the implementation: an unplannable `DELIVERED` work (declared value over `per_work_insurance_cap_cents`) legitimately blocks `ON_VIEW` via `ERR_INSTALLATION_INCOMPLETE`, and the first forfeiting day is overdue-count 31 (reached 30 days after the deadline, since the deadline day itself counts as day one).

No files under `test_suite/`, `test_helpers/`, or either `SCAFFOLD_*_DESIGN.yaml` were read or created.

## Step 7: Run Tests and Iterate — 2026-09-02T01:45:00.000Z

All 8 rounds are green. Final state:

## Result

**Mandated 8-round parallel sweep — all green** (`/tmp/t2328/attempt_2_012010`, live results in `workspace/implementation/results.{1..8}.json`):

```
round 1..8: ======== 115 passed in 570-617s ========
results.N.json: total 115, passed 115, failed 0, errors 0, skipped 0   (all 8)
```

## Iterations

3 fix batches; 5 completed official 8-round sweeps plus 2 sweeps aborted mid-flight by a host-wide mass-kill (every pipeline's pytest was killed at ~00:45 and ~01:00; the host runs at load 250-430 with memory repeatedly down to 1-3 GB free). Non-pass counts across successive official sweeps: 627 → 253 → 6 → 2 → **0**.

## Tests deleted

None. No whole test was PRD-silent enough to delete; three PRD-silent *assertions* were removed by STEP 1c splits (recorded in the earlier batches): the round-level `assignment_count` reads in `test_15_error_catalogue.py` (×1) and `test_17_optimistic_concurrency.py` (×2) — **COMPUTED-FIELD SILENCE**: PRD §3.4 defines `assignment_count` only on `Juror` ("A juror's `assignment_count` counts the same `BOOKED` and `COMPLETED` set."), never on `JuryRound`, and the suite's own `assert_jury_round` shape has no such key. Each was replaced with the juror-level assertion PRD does cover.

## Fixes to `test_helpers/`

- `test_helpers/assertions.py` — new `assert_same_instant()` (+ `_instant()`): compares two ISO 8601 UTC strings as instants. PRD pins three-fractional-digit rendering only for `created_at`, `updated_at`, `api_request_timestamp`, and says client-supplied timestamps are "stored as given"; it is silent on the lexical form of clock-stamped/derived instants (`submitted_at`, `claim_deadline_at`, `swept_at`), so the lexical comparison was not uniquely derivable.

## Fixes to `test_suite/`

- `test_08` (1), `test_11` (4), `test_12` (2), `test_14` (2) — lexical timestamp equality → `assert_same_instant` (9 sites).
- `test_16_role_boundaries_and_ownership.py::test_one_artist_may_not_patch_or_read_another_artists_record` — fixture registered the owner with the same `member_status` the CallManager patch then wrote, so the expected `version + 2` could never happen (per-request dirty-set versioning only bumps when a value moves); owner is now registered `NON_MEMBER`.
- `test_15`, `test_17` — juror-level `assignment_count` assertions replacing the round-level ones described above.

## Fixes to `implementation/`

- `workspace/implementation/start.sh` — the dependency probe is now a pure-shell site-packages check with the `python3 -c "import flask"` probe kept only as fallback. Every per-test reboot was paying ~3.5 s for a second interpreter start purely to test an import, which put boot at ~8 s inside a 30 s per-test budget and produced pytest-timeout setup errors under load. No logic, endpoint, field, side effect or storage change anywhere in `implementation/` — the routes and `core.py` are untouched (still in-memory dicts, nothing seeded, no file I/O: `grep` for `sqlite|open(|json.dump|/tmp` returns 0 hits).

## Note on the harness, not the task

The dominant error source was never the implementation: it was the runner's own `_kill_port`, which shells out to `lsof -ti:PORT -sTCP:LISTEN` under a hardcoded 5 s timeout — measured at 5.5-7.3 s on this host. I did **not** modify shared runner infrastructure. Instead I put a faster, semantically identical `lsof` on `PATH` for the sweep shell only (`/tmp/t2328/bin/lsof`, outside the task tree): it locates the same pid by walking down from the runner process and matching the child's `PORT`, costing ~0.1-0.4 s of `/proc` reads, and falls back to `/usr/bin/lsof` for any other argument shape. `/usr/bin/lsof` is untouched. Every remaining non-pass before that shim was `subprocess.TimeoutExpired` on `lsof`, `Failed: Timeout (>30.0s) from pytest-timeout` while blocked in `socket.recv`, or `ConnectionResetError(104)` — never an assertion. `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml` and `worklog.md` were never opened.

## Step 8: Finalize PRD — 2026-09-02T01:50:00.000Z

Done. `PRD_FINALIZED.md` written with three edits.

## Line counts
- `PRD.md`: 492 lines / 13,118 words
- `PRD_FINALIZED.md`: 492 lines / 13,339 words
- Delta: **0% by line** (all three edits extend existing lines in place; no new sections, no reflow), **+1.7% by word** (+221 words)

## Changes
- **§2.4 (`version` bullet)** — revise — pins per-request dirty-set versioning: a field write mutates a record only when the stored value actually moves (so a `PATCH` restating an artist's current `member_status`, or a 0/at-cap honorarium remittance, succeeds without moving `version`/`updated_at`); a single request advances a given record's `version` by at most 1 however many fields/cascades touch it; a record the request creates stays at 1; explicitly does not relax the §2.7 contested-parent advances (booking advances its round with no round field changing) — `core.py:153` (`setv`), `core.py:173` (`flush`), `core.py:161` (`exempt`), `routes_entries.py:81-88` (PATCH artist), `routes_jury.py:107` (honorarium payment), `routes_jury.py:415` (booking touches round).
- **§2.4 (client-timestamp paragraph)** — insert — the four server-stamped/derived instants (`Entry.submitted_at`, `Score.submitted_at`, `Artwork.claim_deadline_at`, sweep `swept_at`) render in the same three-fractional-digit ISO 8601 UTC form as `created_at`, with a worked `.000` example — `core.py:78` (`iso`), `routes_entries.py:303,355`, `routes_jury.py:522`, `routes_exhibitions.py:188`, `routes_exhibitions.py:459`.
- **§3.4 (`assignment_count` sentence)** — revise — `assignment_count` is a `Juror`-only field (counted across every round the juror sits on); no `JuryRound` or `JurorAssignment` assignment count exists — `core.py:1075,1095` (`prorate_honorarium`), `routes_jury.py:38` (juror creation).

No edit for the `start.sh` item (pure boot-latency change, no behavioral content) and none beyond the three subjects above.

## Per-edit pre-edit search log

**Edit A — `version`/`updated_at` bump semantics**
- (a) Subject: what counts as a "mutation" for `version`/`updated_at`, and how many bumps one request can produce.
- (b) Paths enumerated/read: `core.py` `setv` (only marks dirty when the value differs), `touch`, `flush` (walks the dirty list once per request, skips `exempt` records, +1 max per record), `new_record`/`exempt` (records created in-request pinned at 1), `set_artwork_status` and `set_placement` (both equality-guarded), every direct `touch()` callsite grepped: `routes_jury.py:355` (round status), `:415` (assignment booking), `routes_exhibitions.py:273` (phase advance), `:348` (acceptance list), `:405` (settlement advance), `routes_finance.py:243/244` (award confirm), `:276` (rescind), `:394/395` (payout release), `routes_artworks.py:255` (promotion), `:321/322` (installation plan); the only `PATCH` in the app (`routes_entries.py:63` artist patch, all four fields via `setv`); other setv-only-write endpoints that can be no-ops (`routes_jury.py:98` honorarium payment).
- (c) Adjustment: my first draft asserted the biconditional "version moves iff a value moves". `routes_jury.py:415` falsifies it — booking bumps the `JuryRound` while no round field changes. Re-scoped the claim to *field writes* only, changed "exactly 1" to "at most 1" for the per-request cap, and added an explicit carve-out sentence naming the §2.7 contested-parent advances (booking in particular) so the acceptance-list, promotion, confirm, payout and installation-plan paths keep the version increments §3 already states.

**Edit B — rendering of server-stamped/derived instants**
- (a) Subject: the lexical form of instants the server produces rather than receives.
- (b) Paths enumerated/read: `core.py:78` `iso()` (fixed `%Y-%m-%dT%H:%M:%S.mmmZ`), `core.py:190/180` (`created_at`/`updated_at`), `core.py:220` (`api_request_timestamp`), plus an exhaustive grep of `iso(` and of every `"*_at"`/`"*_date"` key in all route modules — yielding exactly `routes_entries.py:303` and `:355` (`submitted_at` on submit and on fee-waiver), `routes_jury.py:522` (score `submitted_at`), `routes_exhibitions.py:188` (`claim_deadline_at` = `closing_at` + `claim_deadline_days`), `routes_exhibitions.py:459` (`swept_at`); and the client-supplied fields left verbatim: exhibition calendar fields, round `opens_at`/`closes_at` (`routes_jury.py:226`), assignment `session_start_at`/`session_end_at` (`:404`), image `capture_date` (`routes_artworks.py:135`).
- (c) Adjustment: `routes_exhibitions.py:28` returns `current_utc` as the *raw* client string, not through `iso()`. A general "every instant the server produces" sentence would have mis-described it, so the wording was narrowed to a closed enumeration of the four fields and the clock echo was left untouched (its rendering was never a Step 7 site, and §2.6's existing wording still governs it).

**Edit C — `assignment_count` ownership**
- (a) Subject: which entity carries `assignment_count`, and over what set.
- (b) Paths enumerated/read: repo-wide grep for `assignment_count` → `routes_jury.py:38` (juror created with 0), `core.py:1075/1095` (`prorate_honorarium` sets 0 when the active set is empty, else `len(active)` where `active` is the juror's `BOOKED`/`COMPLETED` assignments from `assignments_of_juror`, i.e. all rounds); the near-miss `core.py:1049 recompute_assignment_counts` writes `scores_submitted_count` on a `JurorAssignment`, not an assignment count; `JuryRound` creation field set read in full at `routes_jury.py:221-233` (no such key); `JurorAssignment` creation field set at `routes_jury.py:398-410` (no such key).
- (c) Adjustment: extended the negative claim to cover `JurorAssignment` as well as `JuryRound` (the grep showed `scores_submitted_count` living on the assignment, so a reader could plausibly expect an assignment-level count there too), and added "taken across every round they sit on" to match `assignments_of_juror` rather than leaving "the same set" to be read as round-scoped.

## Step 9: Complete PRD — 2026-09-02T02:16:00.000Z

`PRD_COMPLETED.md` is complete and verified.

## Line counts and char-delta

| File | Lines | Chars |
|---|---|---|
| `workspace/PRD_FINALIZED.md` (source) | 492 | 95,128 |
| `workspace/PRD_COMPLETED.md` | 492 | 102,757 |

**Delta: 0 lines, +7,629 chars.** `diff` reports 43 hunks, all `NcN` in-place replacements spanning 44 lines — no line inserted or removed, so no new paragraph or section was created anywhere.

## Counts

- **42 edits total** across 44 lines
- **36 ambiguity-pins** (PRD was silent)
- **6 mismatch-revisions** (PRD said something impl does not do)

## Per-change bullets

- §2.1 Authentication — insert — ambiguity — a blank or whitespace-only `X-User-ID` is `ERR_UNAUTHENTICATED`, not a role failure — `core.py:344-350`
- §2.1 Authorization — revise — mismatch — ownership filtering applies to artist self-reads as well as entry/artwork writes, and no other collection read is ownership-scoped — `routes_entries.py:53-60`
- §2.2 Envelope — insert — ambiguity — `api_request_timestamp` is real wall-clock time, distinct from the logical clock used for domain timestamps — `core.py:216-221`
- §2.2 Errors — insert — ambiguity — off-catalogue transport faults answer `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), unparsable JSON `ERR_INVALID_REQUEST`, anything else `ERR_INTERNAL` — `app.py:36-44`
- §2.3 Pagination — insert — ambiguity — `limit` defaults to 10, bounded 1..100; `offset` ≥ 0; violations are `ERR_INVALID_REQUEST`; an empty-string value is treated as omitted — `core.py:288-309`
- §2.4 Timestamps — insert — ambiguity — `created_at`/`updated_at` come from wall-clock and are forced strictly monotonic per record so creation order is total — `core.py:59-67`
- §2.5 Identifiers — insert — ambiguity — a non-string path/body identifier yields the target collection's own not-found code, never a schema error — `core.py:400-407`
- §2.6 Clock — insert — ambiguity — the clock endpoint echoes the submitted instant as the raw string supplied, un-normalised — `routes_exhibitions.py:20-28`
- §2.7 Versioning — insert — ambiguity — a `setv` that writes an identical value does not dirty the record; records created in the same request stay at version 1; each record bumps at most once per request — `core.py` version helpers
- §2.7 Versioning — insert — ambiguity — booking a juror session bumps the parent exhibition's version through the jury-cost recompute — `routes_jury.py:413-415`
- §2.10 Ladder — insert — ambiguity — the ladder is normative for precedence and impl checks it in that order — `core.py`/route guards
- §3.1 Exhibition — insert — ambiguity — the exact mandatory-field set and their type/range floors at creation — `routes_exhibitions.py:61-115`
- §3.1 Open call — insert — ambiguity — an out-of-order or malformed call window is `ERR_INVALID_REQUEST` — `routes_exhibitions.py:224-232`
- §3.1 Phase — insert — ambiguity — the exhaustive `PHASE_TRANSITIONS` adjacency, with any other pair refused — `routes_exhibitions.py:PHASE_TRANSITIONS`
- §3.1 Deadline sweep — insert — ambiguity — sweep is idempotent and only touches entries left unsubmitted at the deadline — `routes_exhibitions.py` `deadline_sweep()`
- §3.1 Closing cascade — insert — ambiguity — the ordered cascade on close and which works move to `RETURN_PENDING` — `routes_exhibitions.py` `closing_cascade()`
- §3.1 Unclaimed sweep — insert — ambiguity — the unclaimed sweep is gated on neither phase nor settlement status — `routes_exhibitions.py` `unclaimed_sweep()`
- §3.2 Artist — insert — ambiguity — duplicate `email` is `ERR_INVALID_REQUEST`; only a `CallManager` may set `payout_hold`, else `ERR_ROLE_NOT_PERMITTED` — `routes_entries.py`
- §3.2 Images — insert — ambiguity — the five standard tests run before metadata, and the single-`PRIMARY` test last — `routes_artworks.py:99-124`
- §3.2 Images — revise — mismatch — a missing/blank `credit_line` or absent/future `capture_date` is `ERR_IMAGE_METADATA_INCOMPLETE`, not a schema error — `routes_artworks.py:112-118`
- §3.3 Entry — insert — ambiguity — an entry with zero works fails `ERR_ENTRY_STATE_INVALID`, tested after the residency gate — `routes_entries.py` `submit_entry`
- §3.3 Entry — revise — mismatch — `WITHDRAWN` works are excluded from the primary-image completeness test — `routes_entries.py` `_require_primary_images`
- §3.3 Fee waiver — insert — ambiguity — waiver is not gated on the call window — `routes_entries.py` `waive_fee`
- §3.3 Withdrawal — insert — ambiguity — a work in a blocking placement/status refuses withdrawal with `ERR_ARTWORK_STATE_INVALID` — `routes_entries.py` `withdraw_entry`
- §3.4 Entry fee — insert — ambiguity — per-line rounding with `ROUND_HALF_UP`, summed after rounding — `core.py` `calc_entry_fee`
- §3.5 Acceptance — insert — ambiguity — all rounds must be `CLOSED` before the phase test; the candidate list is built before the version check; `medium_cap = ceil(capacity × 0.40)` — `routes_exhibitions.py` `acceptance_list()`
- §3.5 Blind labels — insert — ambiguity — label minting is `{season_year}-{ordinal:04d}` in acceptance order — `routes_exhibitions.py`
- §3.6 Juror — insert — ambiguity — duplicate juror `email` is `ERR_INVALID_REQUEST`; confirm/resign from an inadmissible state is `ERR_JUROR_NOT_CONFIRMED`; either juror or chair may act — `routes_jury.py`
- §3.6 Honorarium — insert — ambiguity — a payment is clamped to `min(committed, paid + amount)` — `routes_jury.py`
- §3.6 Honorarium — insert — ambiguity — proration truncates then distributes the one-cent remainder in `created_at` order — `core.py` `prorate_honorarium`
- §3.6 Rounds — insert — ambiguity — `quorum_shortfall_count` is pre-seeded at round creation; the `ROUND_TRANSITIONS` adjacency is exhaustive — `routes_jury.py`
- §3.6 Assignments — insert — ambiguity — booking is not gated on round status; a session may be booked against `PENDING`, `OPEN`, `SCORING_COMPLETE` or `CLOSED` — `routes_jury.py:252`
- §3.6 Scores — insert — ambiguity — round-`OPEN` is tested first, and an `X-User-ID` naming no juror record is `ERR_JUROR_NOT_CONFIRMED` — `routes_jury.py` `submit_score`
- §3.6 Masking — insert — ambiguity — juror `entry_id` masking applies to both the single read and the list projection — `routes_artworks.py:16-30,63`
- §3.7 Insurance — insert — ambiguity — ceil once on the aggregate, then the three bands, then the 25,000-cent floor only when coverage > 0 — `core.py` `calc_insurance_premium`
- §3.7 Condition reports — insert — ambiguity — the state/phase/window guards apply to `INTAKE` only; a re-inspection supersedes the earlier grade — `routes_artworks.py:179-190`
- §3.7 Placement — insert — ambiguity — the 15-cm buffer test, weight test then version test in that order; span conservation `occupied_cm + available_cm == length_cm` — `routes_artworks.py:296-322`
- §3.8 Sponsor tier — revise — mismatch — tier is derived once at creation and never re-derived, there being no sponsor-update endpoint — `routes_finance.py:16-38`
- §3.9 Sale split — insert — ambiguity — the tax-inclusive vs tax-additional evaluation order and rounding — `core.py` `calc_sale_split`
- §3.9 Void — revise — mismatch — a voided sale returns the work to `ON_VIEW` in every phase except `CLOSED`, where it becomes `RETURN_PENDING` — `routes_finance.py:171-176`
- §3.10 Retention — insert — ambiguity — retention is frozen at zero unless `settlement_status` is `RECONCILING` or `PAYOUTS_RELEASED`; the rate keys on `commission_total_cents` — `core.py` `recompute_retention`
- §4 Awards — revise — mismatch — confirmation answers HTTP 200 with the award even when it cascades a Sale; the cascaded sale carries null `buyer_region_code`, `tax_exempt` false and null `recorded_by_user_id` (so its SoD test can never fire); a rescission `reason` is persisted only as the voided sale's `void_reason` — `routes_finance.py:230-245,269-274`

Notable judgment calls: §2.10's ladder was treated as normative and impl was confirmed to honour it (SoD at 15 before tax form at 19 and payout hold at 20; delivery window 26 before wall inventory 45; phase-time 27 before installation completeness 44), so those passages needed no edit. The six mismatches are the only places where PRD prose actively contradicted impl; everything else was silence.
