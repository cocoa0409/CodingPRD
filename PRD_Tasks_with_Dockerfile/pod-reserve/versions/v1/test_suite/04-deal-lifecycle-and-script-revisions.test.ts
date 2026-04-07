import {
  getAs,
  postAs,
  putWithVersion,
  postAction,
} from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  expectDealStatus,
  expectDealBudget,
  expectScriptVersion,
  expectReservationStatus,
  expectPodcastInventory,
  expectEpisodeStatus,
  expectReservationInEpisode,
  expectScriptVersionPinned,
  expectReservationNeedsReview,
  expectReservationApproved,
  expectReservationCanceled,
} from '../../../test-helpers/assertions';
import {
  createFixtureStackGeneralStd,
  createFixtureHoldPre30,
  createFixtureApprovedPre30,
  createFixtureSettledPre30,
  createFixtureRestrictedTwoOpenClaims,
  createPodcast,
  createEpisode,
  createDeal,
  createReservation,
  getDeal,
  getPodcast,
  getEpisode,
  updateDeal,
  activateDeal,
  pauseDeal,
  approveReservation,
  cancelReservation,
  submitEpisode,
  publishEpisode,
  findReservation,
} from '../../../test-helpers/resources';
import {
  DEAL_STATUS,
  RESERVATION_STATUS,
  PLACEMENT,
  BRAND_TIER,
  CONTENT_RATING,
  ERROR_CODES,
} from '../../../test-helpers/constants';

describe('Feature 4: Deal Lifecycle and Script Revisions', () => {

  test('DEAL_001: GET /podcasts/:P/deals/:D returns deal fields with status=ACTIVE, script_version=1, budget fields', async () => {

    const { podcast, deal } = await createFixtureStackGeneralStd();

    const res = await getAs(`/podcasts/${podcast.id}/deals/${deal.id}`);

    expectSuccess(res);
    const dealData = res.body.data ?? res.body;
    expect(dealData.status).toBe(DEAL_STATUS.ACTIVE);
    expect(dealData.script_version).toBe(1);
    expect(dealData.budget_total_cents).toBe(5000);
    expect(dealData.budget_available_cents).toBe(5000);
  });

  test('DEAL_002: PUT /podcasts/:P/deals/:D with status=PAUSED changes deal to PAUSED', async () => {

    const { podcast, deal } = await createFixtureStackGeneralStd();
    const dealV2 = await getDeal(podcast.id, deal.id);

    const res = await putWithVersion(
      `/podcasts/${podcast.id}/deals/${deal.id}`,
      { status: DEAL_STATUS.PAUSED },
      dealV2.version
    );

    expectSuccess(res);
    const updatedDeal = await getDeal(podcast.id, deal.id);
    expect(updatedDeal.status).toBe(DEAL_STATUS.PAUSED);
  });

  test('DEAL_003: POST /podcasts/:P/reservations with paused deal has consistent state', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const dealV2 = await getDeal(podcast.id, deal.id);
    await pauseDeal(podcast.id, deal.id, dealV2.version);

    const res = await postAs(`/podcasts/${podcast.id}/reservations`, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    const podcastData = await getPodcast(podcast.id);
    const dealData = await getDeal(podcast.id, deal.id);

    if (res.status >= 200 && res.status < 300) {

      const resData = res.body.data ?? res.body;
      expect(resData.status).toBe(RESERVATION_STATUS.HOLD);
      expect(podcastData.ad_held_seconds).toBe(30);
      expect(dealData.budget_held_cents).toBe(1000);
    } else {

      expect(podcastData.ad_held_seconds).toBe(0);
      expect(dealData.budget_held_cents).toBe(0);
    }
  });

  test('DEAL_004: POST /podcasts/:P/reservations/:R/approve with paused deal fails with ERR_DEAL_NOT_ACTIVE', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();

    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    const dealV2 = await getDeal(podcast.id, deal.id);
    await pauseDeal(podcast.id, deal.id, dealV2.version);

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/approve`,
      reservation.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_DEAL_NOT_ACTIVE);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.HOLD);

    const dealData = await getDeal(podcast.id, deal.id);
    expect(dealData.budget_held_cents).toBe(1000);
    expect(dealData.budget_committed_cents).toBe(0);
  });

  test('DEAL_005: PUT /podcasts/:P/deals/:D with status=ACTIVE resumes paused deal', async () => {

    const { podcast, deal } = await createFixtureStackGeneralStd();
    const dealV2 = await getDeal(podcast.id, deal.id);
    await pauseDeal(podcast.id, deal.id, dealV2.version);
    const dealV3 = await getDeal(podcast.id, deal.id);

    const res = await putWithVersion(
      `/podcasts/${podcast.id}/deals/${deal.id}`,
      { status: DEAL_STATUS.ACTIVE },
      dealV3.version
    );

    expectSuccess(res);
    const updatedDeal = await getDeal(podcast.id, deal.id);
    expect(updatedDeal.status).toBe(DEAL_STATUS.ACTIVE);
  });

  test('DEAL_006: PUT /podcasts/:P/deals/:D with script_text increments script_version and reclassifies APPROVED to NEEDS_REVIEW', async () => {

    const { podcast, episode, deal, reservation } = await createFixtureApprovedPre30();
    const dealV2 = await getDeal(podcast.id, deal.id);

    const res = await putWithVersion(
      `/podcasts/${podcast.id}/deals/${deal.id}`,
      { script_text: 'Read v2' },
      dealV2.version
    );

    expectSuccess(res);

    const updatedDeal = await getDeal(podcast.id, deal.id);
    expect(updatedDeal.script_version).toBe(2);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.NEEDS_REVIEW);
    expect(resv?.script_version_pinned).toBe(1);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_committed_seconds).toBe(30);
  });

  test('DEAL_007: POST /podcasts/:P/episodes/:E/publish fails with ERR_EPISODE_HAS_UNREVIEWED_RESERVATIONS when reservation is NEEDS_REVIEW', async () => {

    const { podcast, episode, deal, reservation } = await createFixtureApprovedPre30();
    const dealV2 = await getDeal(podcast.id, deal.id);

    await updateDeal(podcast.id, deal.id, dealV2.version, { script_text: 'Read v2' });

    const episodeV1 = await getEpisode(podcast.id, episode.id);
    const submittedEpisode = await submitEpisode(podcast.id, episode.id, episodeV1.version);

    const res = await postAction(
      `/podcasts/${podcast.id}/episodes/${episode.id}/publish`,
      submittedEpisode.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_EPISODE_HAS_UNREVIEWED_RESERVATIONS);

    const episodeData = await getEpisode(podcast.id, episode.id);
    expect(episodeData.status).toBe('SUBMITTED');
  });

  test('DEAL_008: POST /podcasts/:P/reservations/:R/approve on NEEDS_REVIEW returns to APPROVED with updated script_version_pinned', async () => {

    const { podcast, episode, deal, reservation } = await createFixtureApprovedPre30();
    const dealV2 = await getDeal(podcast.id, deal.id);

    await updateDeal(podcast.id, deal.id, dealV2.version, { script_text: 'Read v2' });

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resvData = findReservation(episodeData, reservation.id);
    expect(resvData?.status).toBe(RESERVATION_STATUS.NEEDS_REVIEW);

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/approve`,
      resvData!.version
    );

    expectSuccess(res);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    const updatedResv = findReservation(updatedEpisode, reservation.id);
    expect(updatedResv?.status).toBe(RESERVATION_STATUS.APPROVED);
    expect(updatedResv?.script_version_pinned).toBe(2);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_committed_seconds).toBe(30);
  });

  test('DEAL_009: POST /podcasts/:P/episodes/:E/publish succeeds after re-approving NEEDS_REVIEW reservation', async () => {

    const { podcast, episode, deal, reservation } = await createFixtureApprovedPre30();
    const dealV2 = await getDeal(podcast.id, deal.id);

    await updateDeal(podcast.id, deal.id, dealV2.version, { script_text: 'Read v2' });

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resvData = findReservation(episodeData, reservation.id);
    await approveReservation(podcast.id, reservation.id, resvData!.version);

    const episodeV2 = await getEpisode(podcast.id, episode.id);
    const submittedEpisode = await submitEpisode(podcast.id, episode.id, episodeV2.version);

    const res = await postAction(
      `/podcasts/${podcast.id}/episodes/${episode.id}/publish`,
      submittedEpisode.version
    );

    expectSuccess(res);

    const liveEpisode = await getEpisode(podcast.id, episode.id);
    expect(liveEpisode.status).toBe('LIVE');

    const finalResv = findReservation(liveEpisode, reservation.id);
    expect(finalResv?.status).toBe(RESERVATION_STATUS.APPROVED);
    expect(finalResv?.script_version_pinned).toBe(2);
  });

  test('DEAL_010: PUT /podcasts/:P/deals/:D with status=CLOSED closes the deal', async () => {

    const { podcast, deal } = await createFixtureStackGeneralStd();
    const dealV2 = await getDeal(podcast.id, deal.id);

    const res = await putWithVersion(
      `/podcasts/${podcast.id}/deals/${deal.id}`,
      { status: DEAL_STATUS.CLOSED },
      dealV2.version
    );

    expectSuccess(res);
    const updatedDeal = await getDeal(podcast.id, deal.id);
    expect(updatedDeal.status).toBe(DEAL_STATUS.CLOSED);
  });

  test('DEAL_011: Closing deal cancels HOLD reservations and releases inventory/budget', async () => {

    const { podcast, episode, deal, reservation } = await createFixtureHoldPre30();
    const dealV2 = await getDeal(podcast.id, deal.id);

    const res = await putWithVersion(
      `/podcasts/${podcast.id}/deals/${deal.id}`,
      { status: DEAL_STATUS.CLOSED },
      dealV2.version
    );

    expectSuccess(res);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.CANCELED);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_held_seconds).toBe(0);

    const dealData = await getDeal(podcast.id, deal.id);
    expect(dealData.budget_held_cents).toBe(0);
  });

  test('DEAL_012: Closing deal cancels APPROVED reservations and releases commitments', async () => {

    const { podcast, episode, deal, reservation } = await createFixtureApprovedPre30();

    const dealV2 = await getDeal(podcast.id, deal.id);
    expect(dealV2.budget_committed_cents).toBe(1000);

    const res = await putWithVersion(
      `/podcasts/${podcast.id}/deals/${deal.id}`,
      { status: DEAL_STATUS.CLOSED },
      dealV2.version
    );

    expectSuccess(res);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.CANCELED);

    const dealData = await getDeal(podcast.id, deal.id);
    expect(dealData.budget_committed_cents).toBe(0);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_committed_seconds).toBe(0);
  });

  test('DEAL_013: Closing deal preserves SETTLED reservations and budget_spent_cents', async () => {

    const { podcast, episode, deal, reservation } = await createFixtureSettledPre30();

    const dealV2 = await getDeal(podcast.id, deal.id);
    expect(dealV2.budget_spent_cents).toBe(1000);

    const res = await putWithVersion(
      `/podcasts/${podcast.id}/deals/${deal.id}`,
      { status: DEAL_STATUS.CLOSED },
      dealV2.version
    );

    expectSuccess(res);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.SETTLED);

    const dealData = await getDeal(podcast.id, deal.id);
    expect(dealData.budget_spent_cents).toBe(1000);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_committed_seconds).toBe(30);
  });

  test('DEAL_014: Activating deal in RESTRICTED posture fails with ERR_PODCAST_RESTRICTED', async () => {

    const { podcast } = await createFixtureRestrictedTwoOpenClaims();

    const newDeal = await createDeal(podcast.id, {
      advertiser_name: 'New',
      brand_tier: BRAND_TIER.STANDARD,
      budget_total_cents: 5000,
      slot_price_cents: 1000,
      script_text: 'v1',
    });

    const res = await putWithVersion(
      `/podcasts/${podcast.id}/deals/${newDeal.id}`,
      { status: DEAL_STATUS.ACTIVE },
      newDeal.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_PODCAST_RESTRICTED);

    const dealData = await getDeal(podcast.id, newDeal.id);
    expect(dealData.status).toBe(DEAL_STATUS.DRAFT);
  });

  test('DEAL_015: Updating script_text on DRAFT deal in RESTRICTED posture succeeds', async () => {

    const { podcast } = await createFixtureRestrictedTwoOpenClaims();

    const newDeal = await createDeal(podcast.id, {
      advertiser_name: 'New',
      brand_tier: BRAND_TIER.STANDARD,
      budget_total_cents: 5000,
      slot_price_cents: 1000,
      script_text: 'v1',
    });
    const dealV1 = await getDeal(podcast.id, newDeal.id);

    const res = await putWithVersion(
      `/podcasts/${podcast.id}/deals/${newDeal.id}`,
      { script_text: 'v2' },
      dealV1.version
    );

    expectSuccess(res);

    const dealData = await getDeal(podcast.id, newDeal.id);
    expect(dealData.script_version).toBe(2);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.posture).toBe('RESTRICTED');
  });

  test('DEAL_016: Setting ACTIVE deal status to ACTIVE preserves deal state', async () => {

    const { podcast, deal } = await createFixtureStackGeneralStd();
    const dealV2 = await getDeal(podcast.id, deal.id);

    const beforeScriptVersion = dealV2.script_version;
    const beforeBudgetTotal = dealV2.budget_total_cents;
    const beforeBudgetHeld = dealV2.budget_held_cents;
    const beforeBudgetCommitted = dealV2.budget_committed_cents;
    const beforeBudgetSpent = dealV2.budget_spent_cents;
    const beforeBudgetAvailable = dealV2.budget_available_cents;

    const res = await putWithVersion(
      `/podcasts/${podcast.id}/deals/${deal.id}`,
      { status: DEAL_STATUS.ACTIVE },
      dealV2.version
    );

    const updatedDeal = await getDeal(podcast.id, deal.id);
    expect(updatedDeal.status).toBe(DEAL_STATUS.ACTIVE);
    expect(updatedDeal.script_version).toBe(beforeScriptVersion);
    expect(updatedDeal.budget_total_cents).toBe(beforeBudgetTotal);
    expect(updatedDeal.budget_held_cents).toBe(beforeBudgetHeld);
    expect(updatedDeal.budget_committed_cents).toBe(beforeBudgetCommitted);
    expect(updatedDeal.budget_spent_cents).toBe(beforeBudgetSpent);
    expect(updatedDeal.budget_available_cents).toBe(beforeBudgetAvailable);
  });

  test('DEAL_017: PUT brand_tier after creation has consistent state', async () => {

    const { podcast, deal } = await createFixtureStackGeneralStd();
    const dealV2 = await getDeal(podcast.id, deal.id);

    const res = await putWithVersion(
      `/podcasts/${podcast.id}/deals/${deal.id}`,
      { brand_tier: BRAND_TIER.FAMILY_SAFE },
      dealV2.version
    );

    const dealData = await getDeal(podcast.id, deal.id);

    if (res.status >= 200 && res.status < 300) {

      expect(dealData.brand_tier).toBe(BRAND_TIER.FAMILY_SAFE);
    } else {

      expect(dealData.brand_tier).toBe(BRAND_TIER.STANDARD);
    }
  });

  test('DEAL_018: POST /podcasts/:P/reservations with DRAFT deal has consistent state', async () => {

    const { podcast, episode } = await createFixtureStackGeneralStd();

    const draftDeal = await createDeal(podcast.id, {
      advertiser_name: 'DraftDeal',
      brand_tier: BRAND_TIER.STANDARD,
      budget_total_cents: 5000,
      slot_price_cents: 1000,
      script_text: 'v1',
    });

    const res = await postAs(`/podcasts/${podcast.id}/reservations`, {
      episode_id: episode.id,
      deal_id: draftDeal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    const podcastData = await getPodcast(podcast.id);
    const dealData = await getDeal(podcast.id, draftDeal.id);

    if (res.status >= 200 && res.status < 300) {

      const resData = res.body.data ?? res.body;
      expect(resData.status).toBe(RESERVATION_STATUS.HOLD);
      expect(podcastData.ad_held_seconds).toBe(30);
      expect(dealData.budget_held_cents).toBe(1000);
    } else {

      expect(podcastData.ad_held_seconds).toBe(0);
      expect(dealData.budget_held_cents).toBe(0);
    }
  });

  test('DEAL_019: POST /podcasts/:P/reservations succeeds after activating DRAFT deal', async () => {

    const { podcast, episode } = await createFixtureStackGeneralStd();

    const draftDeal = await createDeal(podcast.id, {
      advertiser_name: 'DraftDeal',
      brand_tier: BRAND_TIER.STANDARD,
      budget_total_cents: 5000,
      slot_price_cents: 1000,
      script_text: 'v1',
    });
    const activatedDeal = await activateDeal(podcast.id, draftDeal.id, draftDeal.version);

    const res = await postAs(`/podcasts/${podcast.id}/reservations`, {
      episode_id: episode.id,
      deal_id: activatedDeal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    expectSuccess(res);

    const resData = res.body.data ?? res.body;
    expect(resData.status).toBe(RESERVATION_STATUS.HOLD);

    const dealData = await getDeal(podcast.id, activatedDeal.id);
    expect(dealData.budget_held_cents).toBe(1000);
  });

  test('DEAL_020: POST /podcasts/:P/reservations/:R/settle with paused deal fails with ERR_DEAL_NOT_ACTIVE', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();

    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });
    const approved = await approveReservation(podcast.id, reservation.id, reservation.version);

    const episodeV1 = await getEpisode(podcast.id, episode.id);
    const submitted = await submitEpisode(podcast.id, episode.id, episodeV1.version);
    const published = await publishEpisode(podcast.id, episode.id, submitted.version);

    const dealV2 = await getDeal(podcast.id, deal.id);
    await pauseDeal(podcast.id, deal.id, dealV2.version);

    const liveEpisode = await getEpisode(podcast.id, episode.id);
    const resvAfterPublish = findReservation(liveEpisode, reservation.id);

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/settle`,
      resvAfterPublish!.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_DEAL_NOT_ACTIVE);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.APPROVED);
  });

  test('DEAL_021: Approving NEEDS_REVIEW reservation with paused deal fails with ERR_DEAL_NOT_ACTIVE', async () => {

    const { podcast, episode, deal, reservation } = await createFixtureApprovedPre30();

    const dealV2 = await getDeal(podcast.id, deal.id);
    await updateDeal(podcast.id, deal.id, dealV2.version, { script_text: 'Read v2' });

    let episodeData = await getEpisode(podcast.id, episode.id);
    let resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.NEEDS_REVIEW);

    const dealV3 = await getDeal(podcast.id, deal.id);
    await pauseDeal(podcast.id, deal.id, dealV3.version);

    episodeData = await getEpisode(podcast.id, episode.id);
    resv = findReservation(episodeData, reservation.id);

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/approve`,
      resv!.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_DEAL_NOT_ACTIVE);

    episodeData = await getEpisode(podcast.id, episode.id);
    resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.NEEDS_REVIEW);

    const dealData = await getDeal(podcast.id, deal.id);
    expect(dealData.budget_committed_cents).toBe(1000);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_committed_seconds).toBe(30);
  });

  test('DEAL_022: Multiple script_text updates increment script_version correctly', async () => {

    const { podcast, deal } = await createFixtureStackGeneralStd();

    const dealV2 = await getDeal(podcast.id, deal.id);
    await updateDeal(podcast.id, deal.id, dealV2.version, { script_text: 'Read v2' });
    const dealV3 = await getDeal(podcast.id, deal.id);

    const res = await putWithVersion(
      `/podcasts/${podcast.id}/deals/${deal.id}`,
      { script_text: 'Read v3' },
      dealV3.version
    );

    expectSuccess(res);

    const finalDeal = await getDeal(podcast.id, deal.id);
    expect(finalDeal.script_version).toBe(3);
  });

  test('DEAL_023: Creating second reservation fails with ERR_DEAL_BUDGET_EXCEEDED when budget exhausted', async () => {

    const { podcast, episode } = await createFixtureStackGeneralStd();

    const tinyDeal = await createDeal(podcast.id, {
      advertiser_name: 'Tiny',
      brand_tier: BRAND_TIER.STANDARD,
      budget_total_cents: 1000,
      slot_price_cents: 1000,
      script_text: 'Tiny v1',
    });
    const activatedDeal = await activateDeal(podcast.id, tinyDeal.id, tinyDeal.version);

    const r1 = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: activatedDeal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });
    await approveReservation(podcast.id, r1.id, r1.version);

    const res = await postAs(`/podcasts/${podcast.id}/reservations`, {
      episode_id: episode.id,
      deal_id: activatedDeal.id,
      placement: PLACEMENT.MID_ROLL,
      slot_seconds: 30,
    });

    expectErrorCode(res, ERROR_CODES.ERR_DEAL_BUDGET_EXCEEDED);

    const dealData = await getDeal(podcast.id, activatedDeal.id);
    expect(dealData.budget_committed_cents).toBe(1000);
    expect(dealData.budget_available_cents).toBe(0);
  });

  test('DEAL_024: Approving reservation commits budget correctly', async () => {

    const { podcast, episode } = await createFixtureStackGeneralStd();

    const tinyDeal = await createDeal(podcast.id, {
      advertiser_name: 'Tiny',
      brand_tier: BRAND_TIER.STANDARD,
      budget_total_cents: 1000,
      slot_price_cents: 1000,
      script_text: 'Tiny v1',
    });
    const activatedDeal = await activateDeal(podcast.id, tinyDeal.id, tinyDeal.version);

    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: activatedDeal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/approve`,
      reservation.version
    );

    expectSuccess(res);

    const dealData = await getDeal(podcast.id, activatedDeal.id);
    expect(dealData.budget_committed_cents).toBe(1000);
    expect(dealData.budget_available_cents).toBe(0);
  });

  test('DEAL_025: Canceling reservation releases budget for new reservation', async () => {

    const { podcast, episode } = await createFixtureStackGeneralStd();

    const tinyDeal = await createDeal(podcast.id, {
      advertiser_name: 'Tiny',
      brand_tier: BRAND_TIER.STANDARD,
      budget_total_cents: 1000,
      slot_price_cents: 1000,
      script_text: 'Tiny v1',
    });
    const activatedDeal = await activateDeal(podcast.id, tinyDeal.id, tinyDeal.version);

    const r1 = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: activatedDeal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });
    await cancelReservation(podcast.id, r1.id, r1.version);

    const res = await postAs(`/podcasts/${podcast.id}/reservations`, {
      episode_id: episode.id,
      deal_id: activatedDeal.id,
      placement: PLACEMENT.MID_ROLL,
      slot_seconds: 30,
    });

    expectSuccess(res);

    const dealData = await getDeal(podcast.id, activatedDeal.id);
    expect(dealData.budget_held_cents).toBe(1000);
    expect(dealData.budget_available_cents).toBe(0);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const newResv = episodeData.reservations?.find(r => r.placement === PLACEMENT.MID_ROLL);
    expect(newResv).toBeDefined();
    expect(newResv?.status).toBe(RESERVATION_STATUS.HOLD);
  });

});
