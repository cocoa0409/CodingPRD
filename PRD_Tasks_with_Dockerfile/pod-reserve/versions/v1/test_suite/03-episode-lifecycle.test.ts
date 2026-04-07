import {
  postAs,
  postWithVersion,
  putWithVersion,
  putRaw,
  postAction,
  getAs,
} from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  expectReservationStatus,
  expectPodcastInventory,
  expectEpisodeDraft,
  expectEpisodeSubmitted,
  expectEpisodeLive,
  expectEpisodeRetracted,
  expectEpisodeClear,
  expectEpisodeUnderReview,
  expectEpisodeInventory,
  expectDealBudget,
  expectReservationInEpisode,
  expectPostureNormal,
} from '../../../test-helpers/assertions';
import {
  createPodcast,
  getPodcast,
  getEpisode,
  getDeal,
  createEpisode,
  createReservation,
  approveReservation,
  createFixtureStackGeneralStd,
  createFixtureStackGeneralFamily,
  createFixtureStackLiveStd,
  createFixtureApprovedPre30,
  createFixtureHoldPre30,
  createFixtureSettledPre30,
  createFixtureRestrictedTwoOpenClaims,
  findReservation,
  unwrap,
  createClaim,
  submitEpisode,
  publishEpisode,
} from '../../../test-helpers/resources';
import {
  ERROR_CODES,
  PLACEMENT,
  RESERVATION_STATUS,
  CONTENT_RATING,
  CLAIM_KIND,
} from '../../../test-helpers/constants';

describe('Feature 3: Episode Lifecycle', () => {

  test('EPISODE_001: GET episode returns initial DRAFT status and CLEAR clearance', async () => {

    const { podcast, episode } = await createFixtureStackGeneralStd();

    const res = await getAs(`/podcasts/${podcast.id}/episodes/${episode.id}`);

    expectSuccess(res);
    const ep = unwrap(res.body);
    expect(ep.status).toBe('DRAFT');
    expect(ep.clearance).toBe('CLEAR');
    expect(ep.ad_slots_total_seconds).toBe(60);
    expect(ep.ad_slots_held_seconds).toBe(0);
    expect(ep.ad_slots_committed_seconds).toBe(0);
  });

  test('EPISODE_002: POST /episodes/:E/submit moves episode to SUBMITTED', async () => {

    const { podcast, episode } = await createFixtureStackGeneralStd();
    const ep1 = await getEpisode(podcast.id, episode.id);

    const res = await postAction(
      `/podcasts/${podcast.id}/episodes/${episode.id}/submit`,
      ep1.version
    );

    expectSuccess(res);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    expectEpisodeSubmitted(updatedEpisode);
  });

  test('EPISODE_003: PUT /episodes/:E without If-Match returns ERR_MISSING_IF_MATCH', async () => {

    const { podcast, episode } = await createFixtureStackGeneralStd();

    const res = await putRaw(
      `/podcasts/${podcast.id}/episodes/${episode.id}`,
      { title: 'New Title' }
    );

    expectErrorCode(res, ERROR_CODES.ERR_MISSING_IF_MATCH);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    expect(updatedEpisode.title).toBe('Ep1');
  });

  test('EPISODE_004: PUT /episodes/:E with If-Match updates title and increments version', async () => {

    const { podcast, episode } = await createFixtureStackGeneralStd();
    const ep1 = await getEpisode(podcast.id, episode.id);
    const originalVersion = ep1.version;

    const res = await putWithVersion(
      `/podcasts/${podcast.id}/episodes/${episode.id}`,
      { title: 'New Title' },
      ep1.version
    );

    expectSuccess(res);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    expect(updatedEpisode.title).toBe('New Title');
    expect(updatedEpisode.version).toBe(originalVersion + 1);
  });

  test('EPISODE_005: PUT /episodes/:E on SUBMITTED episode returns ERR_INVALID_STATE', async () => {

    const { podcast, episode } = await createFixtureStackGeneralStd();
    const ep1 = await getEpisode(podcast.id, episode.id);
    const submitted = await submitEpisode(podcast.id, episode.id, ep1.version);

    const res = await putWithVersion(
      `/podcasts/${podcast.id}/episodes/${episode.id}`,
      { title: 'Blocked Edit' },
      submitted.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_INVALID_STATE);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    expect(updatedEpisode.title).toBe('Ep1');
    expectEpisodeSubmitted(updatedEpisode);
  });

  test('EPISODE_006: Episode can be submitted and published to LIVE', async () => {

    const { podcast, episode } = await createFixtureStackGeneralStd();
    const ep1 = await getEpisode(podcast.id, episode.id);
    const submitted = await submitEpisode(podcast.id, episode.id, ep1.version);
    await publishEpisode(podcast.id, episode.id, submitted.version);

    const res = await getAs(`/podcasts/${podcast.id}/episodes/${episode.id}`);

    expectSuccess(res);
    const ep = unwrap(res.body);
    expectEpisodeLive(ep);
  });

  test('EPISODE_007: POST /episodes/:E/publish fails with ERR_EPISODE_HAS_HOLDS when reservation in HOLD', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();

    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    const ep1 = await getEpisode(podcast.id, episode.id);
    const submitted = await submitEpisode(podcast.id, episode.id, ep1.version);

    const res = await postAction(
      `/podcasts/${podcast.id}/episodes/${episode.id}/publish`,
      submitted.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_EPISODE_HAS_HOLDS);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    expectEpisodeSubmitted(updatedEpisode);
    const resv = findReservation(updatedEpisode, reservation.id);
    expect(resv).toBeDefined();
    expectReservationStatus(resv, RESERVATION_STATUS.HOLD);
  });

  test('EPISODE_008: POST /episodes/:E/retract fails with ERR_EPISODE_HAS_HOLDS when HOLD exists', async () => {

    const { podcast, episode, reservation } = await createFixtureHoldPre30();
    const ep1 = await getEpisode(podcast.id, episode.id);
    const submitted = await submitEpisode(podcast.id, episode.id, ep1.version);

    const res = await postAction(
      `/podcasts/${podcast.id}/episodes/${episode.id}/retract`,
      submitted.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_EPISODE_HAS_HOLDS);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    expectEpisodeSubmitted(updatedEpisode);

    const resv = findReservation(updatedEpisode, reservation.id);
    expect(resv).toBeDefined();
    expectReservationStatus(resv, RESERVATION_STATUS.HOLD);
  });

  test('EPISODE_009: POST /episodes/:E/retract on DRAFT returns ERR_INVALID_STATE', async () => {

    const { podcast, episode } = await createFixtureStackGeneralStd();
    const ep1 = await getEpisode(podcast.id, episode.id);

    const res = await postAction(
      `/podcasts/${podcast.id}/episodes/${episode.id}/retract`,
      ep1.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_INVALID_STATE);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    expectEpisodeDraft(updatedEpisode);
  });

  test('EPISODE_010: POST /episodes/:E/publish succeeds with APPROVED reservation', async () => {

    const { podcast, episode, reservation } = await createFixtureApprovedPre30();
    const ep1 = await getEpisode(podcast.id, episode.id);
    const submitted = await submitEpisode(podcast.id, episode.id, ep1.version);

    const res = await postAction(
      `/podcasts/${podcast.id}/episodes/${episode.id}/publish`,
      submitted.version
    );

    expectSuccess(res);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    expectEpisodeLive(updatedEpisode);
    const resv = findReservation(updatedEpisode, reservation.id);
    expect(resv).toBeDefined();
    expectReservationStatus(resv, RESERVATION_STATUS.APPROVED);
  });

  test('EPISODE_011: POST /episodes/:E/retract on LIVE episode succeeds', async () => {

    const { podcast, episode } = await createFixtureStackLiveStd();
    const ep3 = await getEpisode(podcast.id, episode.id);

    const res = await postAction(
      `/podcasts/${podcast.id}/episodes/${episode.id}/retract`,
      ep3.version
    );

    expectSuccess(res);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    expectEpisodeRetracted(updatedEpisode);
  });

  test('EPISODE_012: POST /episodes/:E/retract credits SETTLED reservation and reverses budget', async () => {

    const { podcast, episode, deal, reservation } = await createFixtureSettledPre30();

    const ep3 = await getEpisode(podcast.id, episode.id);
    const dealBefore = await getDeal(podcast.id, deal.id);
    const podcastBefore = await getPodcast(podcast.id);

    const spentBefore = dealBefore.budget_spent_cents;
    const committedSecondsBefore = podcastBefore.ad_committed_seconds;
    expect(spentBefore).toBeGreaterThan(0);
    expect(committedSecondsBefore).toBeGreaterThan(0);

    const res = await postAction(
      `/podcasts/${podcast.id}/episodes/${episode.id}/retract`,
      ep3.version
    );

    expectSuccess(res);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    expectEpisodeRetracted(updatedEpisode);
    const resv = findReservation(updatedEpisode, reservation.id);
    expect(resv).toBeDefined();
    expectReservationStatus(resv, RESERVATION_STATUS.CREDITED);

    const updatedDeal = await getDeal(podcast.id, deal.id);
    expect(updatedDeal.budget_spent_cents).toBe(0);
    expect(updatedDeal.budget_available_cents).toBe(dealBefore.budget_total_cents);

    const updatedPodcast = await getPodcast(podcast.id);
    expect(updatedPodcast.ad_committed_seconds).toBe(0);
    expect(updatedPodcast.ad_available_seconds).toBe(podcastBefore.ad_capacity_seconds);
  });

  test('EPISODE_013: POST /episodes/:E/retract cancels APPROVED reservation and releases commitment', async () => {

    const { podcast, episode, deal, reservation } = await createFixtureApprovedPre30();
    const ep1 = await getEpisode(podcast.id, episode.id);
    const submitted = await submitEpisode(podcast.id, episode.id, ep1.version);
    const published = await publishEpisode(podcast.id, episode.id, submitted.version);

    const podcastBefore = await getPodcast(podcast.id);
    expect(podcastBefore.ad_committed_seconds).toBe(30);

    const res = await postAction(
      `/podcasts/${podcast.id}/episodes/${episode.id}/retract`,
      published.version
    );

    expectSuccess(res);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(updatedEpisode, reservation.id);
    expect(resv).toBeDefined();
    expectReservationStatus(resv, RESERVATION_STATUS.CANCELED);

    const updatedPodcast = await getPodcast(podcast.id);
    expect(updatedPodcast.ad_committed_seconds).toBe(0);

    const updatedDeal = await getDeal(podcast.id, deal.id);
    expect(updatedDeal.budget_committed_cents).toBe(0);
  });

  test('EPISODE_014: PUT /episodes/:E tightening capacity causes APPROVED to become OVERBOOKED', async () => {

    const { podcast, episode, deal, reservation } = await createFixtureApprovedPre30();
    const ep1 = await getEpisode(podcast.id, episode.id);

    const res = await putWithVersion(
      `/podcasts/${podcast.id}/episodes/${episode.id}`,
      { ad_slots_total_seconds: 20 },
      ep1.version
    );

    expectSuccess(res);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    expect(updatedEpisode.ad_slots_total_seconds).toBe(20);
    const resv = findReservation(updatedEpisode, reservation.id);
    expect(resv).toBeDefined();
    expectReservationStatus(resv, RESERVATION_STATUS.OVERBOOKED);

    const updatedPodcast = await getPodcast(podcast.id);
    expect(updatedPodcast.ad_committed_seconds).toBe(0);

    const updatedDeal = await getDeal(podcast.id, deal.id);
    expect(updatedDeal.budget_committed_cents).toBe(0);
  });

  test('EPISODE_015: PUT /episodes/:E tightening capacity bumps most recent approval to OVERBOOKED', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();

    const r1 = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });
    const r1Approved = await approveReservation(podcast.id, r1.id, r1.version);

    const r2 = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.MID_ROLL,
      slot_seconds: 30,
    });
    const r2Approved = await approveReservation(podcast.id, r2.id, r2.version);

    const podcastBefore = await getPodcast(podcast.id);
    expect(podcastBefore.ad_committed_seconds).toBe(60);

    const ep1 = await getEpisode(podcast.id, episode.id);

    const res = await putWithVersion(
      `/podcasts/${podcast.id}/episodes/${episode.id}`,
      { ad_slots_total_seconds: 30 },
      ep1.version
    );

    expectSuccess(res);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    const resv1 = findReservation(updatedEpisode, r1.id);
    const resv2 = findReservation(updatedEpisode, r2.id);

    expect(resv1).toBeDefined();
    expect(resv2).toBeDefined();

    expectReservationStatus(resv1, RESERVATION_STATUS.APPROVED);

    expectReservationStatus(resv2, RESERVATION_STATUS.OVERBOOKED);

    const updatedPodcast = await getPodcast(podcast.id);
    expect(updatedPodcast.ad_committed_seconds).toBe(30);
  });

  test('EPISODE_016: PUT /episodes/:E tightening to 0 cancels HOLD reservation', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();

    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    const ep1 = await getEpisode(podcast.id, episode.id);

    const res = await putWithVersion(
      `/podcasts/${podcast.id}/episodes/${episode.id}`,
      { ad_slots_total_seconds: 0 },
      ep1.version
    );

    expectSuccess(res);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(updatedEpisode, reservation.id);
    expect(resv).toBeDefined();
    expectReservationStatus(resv, RESERVATION_STATUS.CANCELED);

    const updatedPodcast = await getPodcast(podcast.id);
    expect(updatedPodcast.ad_held_seconds).toBe(0);

    const updatedDeal = await getDeal(podcast.id, deal.id);
    expect(updatedDeal.budget_held_cents).toBe(0);
  });

  test('EPISODE_017: PUT /episodes/:E can change content_rating to MATURE', async () => {

    const { podcast, episode } = await createFixtureStackGeneralStd();
    const ep1 = await getEpisode(podcast.id, episode.id);

    const res = await putWithVersion(
      `/podcasts/${podcast.id}/episodes/${episode.id}`,
      { content_rating: CONTENT_RATING.MATURE },
      ep1.version
    );

    expectSuccess(res);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    expect(updatedEpisode.content_rating).toBe(CONTENT_RATING.MATURE);
  });

  test('EPISODE_018: PUT /episodes/:E changing to MATURE moves FAMILY_SAFE reservation to NEEDS_REVIEW', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralFamily();

    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });
    const approved = await approveReservation(podcast.id, reservation.id, reservation.version);

    const ep1 = await getEpisode(podcast.id, episode.id);

    const res = await putWithVersion(
      `/podcasts/${podcast.id}/episodes/${episode.id}`,
      { content_rating: CONTENT_RATING.MATURE },
      ep1.version
    );

    expectSuccess(res);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(updatedEpisode, reservation.id);
    expect(resv).toBeDefined();
    expectReservationStatus(resv, RESERVATION_STATUS.NEEDS_REVIEW);

    const updatedPodcast = await getPodcast(podcast.id);
    expect(updatedPodcast.ad_committed_seconds).toBe(30);
  });

  test('EPISODE_019: POST /reservations/:R/approve fails with ERR_BRAND_SAFETY_MISMATCH on MATURE episode', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralFamily();

    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });
    const approved = await approveReservation(podcast.id, reservation.id, reservation.version);

    const ep1 = await getEpisode(podcast.id, episode.id);
    await putWithVersion(
      `/podcasts/${podcast.id}/episodes/${episode.id}`,
      { content_rating: CONTENT_RATING.MATURE },
      ep1.version
    );

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    const resvNeedsReview = findReservation(updatedEpisode, reservation.id);

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/approve`,
      resvNeedsReview!.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_BRAND_SAFETY_MISMATCH);

    const finalEpisode = await getEpisode(podcast.id, episode.id);
    const finalResv = findReservation(finalEpisode, reservation.id);
    expectReservationStatus(finalResv, RESERVATION_STATUS.NEEDS_REVIEW);
  });

  test('EPISODE_021: POST /episodes/:E/submit on SUBMITTED returns ERR_INVALID_STATE', async () => {

    const { podcast, episode } = await createFixtureStackGeneralStd();
    const ep1 = await getEpisode(podcast.id, episode.id);
    const submitted = await submitEpisode(podcast.id, episode.id, ep1.version);

    const res = await postAction(
      `/podcasts/${podcast.id}/episodes/${episode.id}/submit`,
      submitted.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_INVALID_STATE);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    expectEpisodeSubmitted(updatedEpisode);
  });

  test('EPISODE_022: POST /episodes/:E/publish fails with ERR_EPISODE_UNDER_REVIEW when claim open', async () => {

    const { podcast, episode } = await createFixtureStackGeneralStd();

    await createClaim(podcast.id, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });

    const ep1 = await getEpisode(podcast.id, episode.id);
    const submitted = await submitEpisode(podcast.id, episode.id, ep1.version);

    const res = await postAction(
      `/podcasts/${podcast.id}/episodes/${episode.id}/publish`,
      submitted.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_EPISODE_UNDER_REVIEW);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    expectEpisodeSubmitted(updatedEpisode);
    expectEpisodeUnderReview(updatedEpisode);
  });

  test('EPISODE_023: POST /episodes/:E/publish fails with ERR_PODCAST_RESTRICTED when podcast restricted', async () => {

    const { podcast, episode1 } = await createFixtureRestrictedTwoOpenClaims();

    const cleanEpisode = await createEpisode(podcast.id, {
      title: 'CleanEp',
      content_rating: CONTENT_RATING.GENERAL,
      ad_slots_total_seconds: 60,
    });

    const ep1 = await getEpisode(podcast.id, cleanEpisode.id);
    const submitted = await submitEpisode(podcast.id, cleanEpisode.id, ep1.version);

    const res = await postAction(
      `/podcasts/${podcast.id}/episodes/${cleanEpisode.id}/publish`,
      submitted.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_PODCAST_RESTRICTED);

    const updatedEpisode = await getEpisode(podcast.id, cleanEpisode.id);
    expectEpisodeSubmitted(updatedEpisode);
  });

  test('EPISODE_024: POST /reservations/:R/settle fails with ERR_EPISODE_UNDER_REVIEW when claim open', async () => {

    const { podcast, episode, reservation } = await createFixtureApprovedPre30();
    const ep1 = await getEpisode(podcast.id, episode.id);
    const submitted = await submitEpisode(podcast.id, episode.id, ep1.version);
    await publishEpisode(podcast.id, episode.id, submitted.version);

    await createClaim(podcast.id, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(updatedEpisode, reservation.id);

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/settle`,
      resv!.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_EPISODE_UNDER_REVIEW);

    const finalEpisode = await getEpisode(podcast.id, episode.id);
    const finalResv = findReservation(finalEpisode, reservation.id);
    expectReservationStatus(finalResv, RESERVATION_STATUS.APPROVED);
  });

  test('EPISODE_025: GET /podcasts/:P shows inventory unchanged after creating episode', async () => {

    const { podcast } = await createFixtureStackGeneralStd();
    const podcastBefore = await getPodcast(podcast.id);

    await createEpisode(podcast.id, {
      title: 'Ep2',
      content_rating: CONTENT_RATING.GENERAL,
      ad_slots_total_seconds: 60,
    });

    const res = await getAs(`/podcasts/${podcast.id}`);

    expectSuccess(res);
    const p = unwrap(res.body);
    expectPostureNormal(p);
    expect(p.ad_held_seconds).toBe(0);
    expect(p.ad_committed_seconds).toBe(0);

    expect(p.ad_available_seconds).toBe(podcastBefore.ad_capacity_seconds);
  });

});
