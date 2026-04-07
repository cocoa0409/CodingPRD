import {
  apiClient,
  buildUserHeaders,
  handleApiResponse,
  validateApiResponseStructure,
  validateErrorEnvelope,
  assertGardenPlan,
  assertPlantingSeason,
  assertPlantingTask,
  assertGardenPlot,
  generateGardenPlanPayload,
  generatePlantingSeasonPayload,
  generatePlantingTaskPayload,
  generateGardenPlotPayload,
  generateAppliedDate,
  GardenPlan,
  PlantingSeason,
  PlantingTask,
  GardenPlot,
  TaskAssignment,
  GardenPlanStatus,
  PlantingSeasonStatus,
  UserRole,
  AmendmentName,
  ApiErrorId, RequiredAmendment,
  ApiHeaders
} from '../../../test-helpers';

describe('Phase 1: Endpoint Validation', () => {
  const gardenManagerHeaders = buildUserHeaders('gm-1', UserRole.GardenManager);
  const gardenerHeaders = buildUserHeaders('gardener-1', UserRole.Gardener);
  const billingAdminHeaders = buildUserHeaders('billing-1', UserRole.BillingAdmin);

  const NON_EXISTENT_UUID = '00000000-0000-0000-0000-000000000000';

  async function fetchAllPlans(headers: ApiHeaders): Promise<GardenPlan[]> {
    let offset = 0;
    const all: GardenPlan[] = [];
    while (true) {
      const res = await apiClient.getGardenPlans(headers, { limit: 100, offset });
      const envelope = validateApiResponseStructure<GardenPlan[]>(res, { expectPaginated: true });
      all.push(...envelope.data);
      if (!envelope.meta.has_more) break;
      offset += envelope.meta.limit ?? 0;
    }
    return all;
  }

  describe('GardenPlan Resource', () => {
    it('should create a new Garden Plan', async () => {
      const payload = {
        plan_name: 'Spring Community Garden 2024',
        total_water_credits: 10000.00,
      };

      const res = await apiClient.createGardenPlan(payload, gardenManagerHeaders);
      const plan = handleApiResponse<GardenPlan>(res, 201);

      assertGardenPlan(plan);

      expect(plan.plan_name).toBe('Spring Community Garden 2024');
      expect(plan.total_water_credits).toBe(10000.00);
      expect(plan.status).toBe(GardenPlanStatus.PLANNING);
      expect(plan.water_credits_balance).toBe(10000.00);
      expect(plan.pest_risk_score).toBe(0);
    });

    it('should list all Garden Plans', async () => {
      const plan1Payload = { plan_name: 'North Garden', total_water_credits: 5000 };
      const plan2Payload = { plan_name: 'South Garden', total_water_credits: 7500 };

      const res1 = await apiClient.createGardenPlan(plan1Payload, gardenManagerHeaders);
      const plan1 = handleApiResponse<GardenPlan>(res1, 201);

      const res2 = await apiClient.createGardenPlan(plan2Payload, gardenManagerHeaders);
      const plan2 = handleApiResponse<GardenPlan>(res2, 201);

      const plans = await fetchAllPlans(gardenManagerHeaders);

      expect(plans.length).toBeGreaterThanOrEqual(2);
      const planIds = plans.map(p => p.id);
      expect(planIds).toContain(plan1.id);
      expect(planIds).toContain(plan2.id);
    });

    describe('Pagination for Garden Plans', () => {
      beforeEach(async () => {
        await apiClient.createGardenPlan({ plan_name: 'Pagination Garden 1', total_water_credits: 5000 }, gardenManagerHeaders);
        await apiClient.createGardenPlan({ plan_name: 'Pagination Garden 2', total_water_credits: 5000 }, gardenManagerHeaders);
        await apiClient.createGardenPlan({ plan_name: 'Pagination Garden 3', total_water_credits: 5000 }, gardenManagerHeaders);
      });

      it('should respect the limit parameter', async () => {
        const listRes = await apiClient.getGardenPlans(gardenManagerHeaders, { limit: 2 });
        const plans = handleApiResponse<GardenPlan[]>(listRes, 200, { expectPaginated: true });
        expect(plans.length).toBe(2);
      });

      it('should respect the offset parameter', async () => {
        const fullListRes = await apiClient.getGardenPlans(gardenManagerHeaders, { limit: 100 });
        const fullList = handleApiResponse<GardenPlan[]>(fullListRes, 200, { expectPaginated: true });
        const secondPlanId = fullList[1].id;

        const listRes = await apiClient.getGardenPlans(gardenManagerHeaders, { limit: 1, offset: 1 });
        const plans = handleApiResponse<GardenPlan[]>(listRes, 200, { expectPaginated: true });

        expect(plans.length).toBe(1);
        expect(plans[0].id).toBe(secondPlanId);
      });
    });

    it('should get a specific Garden Plan', async () => {
      const payload = { plan_name: 'Test Community Garden', total_water_credits: 8000 };
      const createRes = await apiClient.createGardenPlan(payload, gardenManagerHeaders);
      const createdPlan = handleApiResponse<GardenPlan>(createRes, 201);

      const getRes = await apiClient.getGardenPlan(createdPlan.id, gardenManagerHeaders);
      const retrievedPlan = handleApiResponse<GardenPlan>(getRes, 200);

      assertGardenPlan(retrievedPlan);
      expect(retrievedPlan.id).toBe(createdPlan.id);
      expect(retrievedPlan.plan_name).toBe('Test Community Garden');
    });

    it('should not get a non-existent Garden Plan', async () => {
      const res1 = await apiClient.getGardenPlan(NON_EXISTENT_UUID, gardenManagerHeaders);
      validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_FOUND });

      const res2 = await apiClient.activateGardenPlan(NON_EXISTENT_UUID, gardenManagerHeaders);
      validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_FOUND });
    });
  });

  describe('PlantingSeason Resource', () => {
    let testPlan: GardenPlan;

    beforeEach(async () => {
      const planRes = await apiClient.createGardenPlan(
        { plan_name: 'Season Test Garden', total_water_credits: 10000 },
        gardenManagerHeaders
      );
      testPlan = handleApiResponse<GardenPlan>(planRes, 201);

      const activateRes = await apiClient.activateGardenPlan(testPlan.id, gardenManagerHeaders);
      testPlan = handleApiResponse<GardenPlan>(activateRes, 200);
    });

    it('should create a Season under an existing Plan', async () => {
      const payload = {
        name: 'Spring Planting',
        start_date: 90,
        end_date: 180,
      };

      const res = await apiClient.createPlantingSeason(testPlan.id, payload, gardenerHeaders);
      const season = handleApiResponse<PlantingSeason>(res, 201);

      assertPlantingSeason(season);
      expect(season.name).toBe('Spring Planting');
      expect(season.plan_id).toBe(testPlan.id);
      expect(season.status).toBe(PlantingSeasonStatus.PLANNING);
    });

    it('should not perform operations on a non-existent Plan', async () => {
      const payload = generatePlantingSeasonPayload();
      const res1 = await apiClient.createPlantingSeason(NON_EXISTENT_UUID, payload, gardenerHeaders);
      validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_FOUND });

      const res2 = await apiClient.getPlantingSeasons(NON_EXISTENT_UUID, gardenManagerHeaders);
      validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_FOUND });

      const seasonRes = await apiClient.createPlantingSeason(
        testPlan.id,
        generatePlantingSeasonPayload(),
        gardenerHeaders
      );
      const season = handleApiResponse<PlantingSeason>(seasonRes, 201);

      const res3 = await apiClient.getPlantingSeason(NON_EXISTENT_UUID, season.id, gardenManagerHeaders);
      validateErrorEnvelope(res3, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_FOUND });
    });

    describe('Pagination for Planting Seasons', () => {
      beforeEach(async () => {
        await apiClient.createPlantingSeason(testPlan.id, { name: 'Spring Season', start_date: 60, end_date: 150 }, gardenerHeaders);
        await apiClient.createPlantingSeason(testPlan.id, { name: 'Summer Season', start_date: 151, end_date: 240 }, gardenerHeaders);
        await apiClient.createPlantingSeason(testPlan.id, { name: 'Fall Season', start_date: 241, end_date: 330 }, gardenerHeaders);
      });

      it('should respect the limit parameter for seasons', async () => {
        const listRes = await apiClient.getPlantingSeasons(testPlan.id, gardenManagerHeaders, { limit: 1 });
        const seasons = handleApiResponse<PlantingSeason[]>(listRes, 200, { expectPaginated: true });
        expect(seasons.length).toBe(1);
      });

      it('should accept requests with limit=100', async () => {
        const res = await apiClient.getPlantingSeasons(testPlan.id, gardenManagerHeaders, { limit: 100 });

        expect(res.status).toBe(200);
        const seasons = handleApiResponse<PlantingSeason[]>(res, 200, { expectPaginated: true });
        expect(seasons.length).toBeLessThanOrEqual(100);
      });

      it('should respect the offset parameter for seasons', async () => {
        const fullListRes = await apiClient.getPlantingSeasons(testPlan.id, gardenManagerHeaders);
        const fullList = handleApiResponse<PlantingSeason[]>(fullListRes, 200, { expectPaginated: true });
        const secondSeasonId = fullList[1].id;

        const listRes = await apiClient.getPlantingSeasons(testPlan.id, gardenManagerHeaders, { limit: 1, offset: 1 });
        const seasons = handleApiResponse<PlantingSeason[]>(listRes, 200, { expectPaginated: true });

        expect(seasons.length).toBe(1);
        expect(seasons[0].id).toBe(secondSeasonId);
      });
    });

    it('should get a specific existing Season', async () => {
      const seasonPayload = { name: 'Test Season', start_date: 100, end_date: 200 };
      const createRes = await apiClient.createPlantingSeason(testPlan.id, seasonPayload, gardenerHeaders);
      const createdSeason = handleApiResponse<PlantingSeason>(createRes, 201);

      const getRes = await apiClient.getPlantingSeason(testPlan.id, createdSeason.id, gardenManagerHeaders);
      const retrievedSeason = handleApiResponse<PlantingSeason>(getRes, 200);

      assertPlantingSeason(retrievedSeason);
      expect(retrievedSeason.id).toBe(createdSeason.id);
      expect(retrievedSeason.name).toBe('Test Season');
    });

    it('should not perform operations on a non-existent Season', async () => {
      const res1 = await apiClient.getPlantingSeason(testPlan.id, NON_EXISTENT_UUID, gardenManagerHeaders);
      validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_SEASON_NOT_FOUND });

      const res2 = await apiClient.updatePlantingSeasonStatus(
        testPlan.id,
        NON_EXISTENT_UUID,
        { status: PlantingSeasonStatus.READY_FOR_PLANTING },
        gardenManagerHeaders
      );
      validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_SEASON_NOT_FOUND });
    });

    it('should handle data isolation for a Season from a different plan', async () => {
      const planBRes = await apiClient.createGardenPlan(
        { plan_name: 'Plan B Garden', total_water_credits: 5000 },
        gardenManagerHeaders
      );
      let planB = handleApiResponse<GardenPlan>(planBRes, 201);

      planB = handleApiResponse<GardenPlan>(
        await apiClient.activateGardenPlan(planB.id, gardenManagerHeaders),
        200
      );

      const seasonRes = await apiClient.createPlantingSeason(
        planB.id,
        { name: 'Plan B Season', start_date: 100, end_date: 200 },
        gardenerHeaders
      );
      const seasonB = handleApiResponse<PlantingSeason>(seasonRes, 201);

      const res = await apiClient.getPlantingSeason(testPlan.id, seasonB.id, gardenManagerHeaders);
      validateErrorEnvelope(res, {
        expectedErrorId: ApiErrorId.ERR_SEASON_NOT_FOUND,
      });
    });

    it('should handle data isolation when updating a Season from different plan', async () => {
      const planBRes = await apiClient.createGardenPlan(
        { plan_name: 'Plan B Garden', total_water_credits: 5000 },
        gardenManagerHeaders
      );
      let planB = handleApiResponse<GardenPlan>(planBRes, 201);

      planB = handleApiResponse<GardenPlan>(
        await apiClient.activateGardenPlan(planB.id, gardenManagerHeaders),
        200
      );

      const seasonRes = await apiClient.createPlantingSeason(
        planB.id,
        generatePlantingSeasonPayload(),
        gardenerHeaders
      );
      const seasonB = handleApiResponse<PlantingSeason>(seasonRes, 201);

      const res = await apiClient.updatePlantingSeasonStatus(
        testPlan.id,
        seasonB.id,
        { status: PlantingSeasonStatus.READY_FOR_PLANTING },
        gardenManagerHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_SEASON_NOT_FOUND });
    });
  });

  describe('PlantingTask Resource', () => {
    let plan: GardenPlan;
    let season: PlantingSeason;

    beforeEach(async () => {
      const planRes = await apiClient.createGardenPlan(
        { plan_name: 'Task Test Garden', total_water_credits: 10000 },
        gardenManagerHeaders
      );
      plan = handleApiResponse<GardenPlan>(planRes, 201);

      const activateRes = await apiClient.activateGardenPlan(plan.id, gardenManagerHeaders);
      plan = handleApiResponse<GardenPlan>(activateRes, 200);

      const seasonRes = await apiClient.createPlantingSeason(
        plan.id,
        { name: 'Task Test Season', start_date: 100, end_date: 200 },
        gardenerHeaders
      );
      season = handleApiResponse<PlantingSeason>(seasonRes, 201);
    });

    it('should not create a Task with invalid dates', async () => {
      const taskPayload1 = {
        plant_type: 'Roma Tomato',
        plant_family: 'Solanaceae',
        required_amendment: RequiredAmendment.NONE,
        start_date: 150,
        end_date: 120,
        water_requirement_liters: 50,
      };
      const res1 = await apiClient.createPlantingTask(
        plan.id,
        season.id,
        taskPayload1,
        gardenerHeaders
      );
      validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_INVALID_TASK_DATES });

      const taskPayload2 = {
        plant_type: 'Bell Pepper',
        plant_family: 'Solanaceae',
        required_amendment: RequiredAmendment.NONE,
        start_date: 130,
        end_date: 130,
        water_requirement_liters: 40,
      };
      const res2 = await apiClient.createPlantingTask(
        plan.id,
        season.id,
        taskPayload2,
        gardenerHeaders
      );
      validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_INVALID_TASK_DATES });
    });

    it('should not create a Task under a non-existent Season', async () => {
      const taskPayload = generatePlantingTaskPayload();
      const res = await apiClient.createPlantingTask(
        plan.id,
        NON_EXISTENT_UUID,
        taskPayload,
        gardenerHeaders
      );
      validateErrorEnvelope(res, {
        expectedErrorId: ApiErrorId.ERR_SEASON_NOT_FOUND
      });
    });

    it('should get a specific existing Task', async () => {
      const taskPayload = {
        plant_type: 'Heirloom Carrots',
        plant_family: 'Apiaceae',
        required_amendment: RequiredAmendment.NONE,
        start_date: 110,
        end_date: 170,
        water_requirement_liters: 30,
      };
      const createRes = await apiClient.createPlantingTask(
        plan.id,
        season.id,
        taskPayload,
        gardenerHeaders
      );
      const createdTask = handleApiResponse<PlantingTask>(createRes, 201);

      const getRes = await apiClient.getPlantingTask(
        plan.id,
        season.id,
        createdTask.id,
        gardenManagerHeaders
      );
      const retrievedTask = handleApiResponse<PlantingTask>(getRes, 200);

      assertPlantingTask(retrievedTask);
      expect(retrievedTask.id).toBe(createdTask.id);
      expect(retrievedTask.plant_type).toBe('Heirloom Carrots');
    });

    it('should not get a non-existent Task', async () => {
      const res = await apiClient.getPlantingTask(
        plan.id,
        season.id,
        NON_EXISTENT_UUID,
        gardenManagerHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_TASK_NOT_FOUND });
    });

    it('should handle data isolation when getting a task from the wrong season', async () => {
      const seasonARes = await apiClient.createPlantingSeason(
        plan.id,
        { name: 'Season A', start_date: 50, end_date: 100 },
        gardenerHeaders
      );
      const seasonA = handleApiResponse<PlantingSeason>(seasonARes, 201);

      const seasonBRes = await apiClient.createPlantingSeason(
        plan.id,
        { name: 'Season B', start_date: 101, end_date: 150 },
        gardenerHeaders
      );
      const seasonB = handleApiResponse<PlantingSeason>(seasonBRes, 201);

      const taskRes = await apiClient.createPlantingTask(
        plan.id,
        seasonB.id,
        {
          plant_type: 'Season B Tomatoes',
          plant_family: 'Solanaceae',
          required_amendment: RequiredAmendment.NONE,
          start_date: 110,
          end_date: 140,
          water_requirement_liters: 50,
        },
        gardenerHeaders
      );
      const taskB = handleApiResponse<PlantingTask>(taskRes, 201);

      const res = await apiClient.getPlantingTask(
        plan.id,
        seasonA.id,
        taskB.id,
        gardenManagerHeaders
      );

      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_TASK_NOT_FOUND });
    });

    it('should handle data isolation when getting a task from a different plan', async () => {
      const planBRes = await apiClient.createGardenPlan(
        { plan_name: 'Plan B Garden', total_water_credits: 5000 },
        gardenManagerHeaders
      );
      let planB = handleApiResponse<GardenPlan>(planBRes, 201);

      planB = handleApiResponse<GardenPlan>(
        await apiClient.activateGardenPlan(planB.id, gardenManagerHeaders),
        200
      );

      const seasonBRes = await apiClient.createPlantingSeason(
        planB.id,
        { name: 'Season B', start_date: 100, end_date: 200 },
        gardenerHeaders
      );
      const seasonB = handleApiResponse<PlantingSeason>(seasonBRes, 201);

      const taskBRes = await apiClient.createPlantingTask(
        planB.id,
        seasonB.id,
        {
          plant_type: 'Plan B Lettuce',
          plant_family: 'Asteraceae',
          required_amendment: RequiredAmendment.NONE,
          start_date: 110,
          end_date: 140,
          water_requirement_liters: 25,
        },
        gardenerHeaders
      );
      const taskB = handleApiResponse<PlantingTask>(taskBRes, 201);

      const res = await apiClient.getPlantingTask(
        plan.id,
        seasonB.id,
        taskB.id,
        gardenManagerHeaders
      );

      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_SEASON_NOT_FOUND });
    });
  });

  describe('GardenPlot Resource', () => {
    it('should create a new Garden Plot', async () => {
      const planRes = await apiClient.createGardenPlan(
        generateGardenPlanPayload(),
        gardenManagerHeaders
      );
      let plan = handleApiResponse<GardenPlan>(planRes, 201);

      const activateRes = await apiClient.activateGardenPlan(plan.id, gardenManagerHeaders);
      plan = handleApiResponse<GardenPlan>(activateRes, 200);

      const plotPayload = {
        plot_name: 'Sunny Corner Plot',
        plot_size_sqm: 25.5,
        water_credits_per_liter: 2.5,
      };

      const res = await apiClient.createGardenPlot(
        plan.id,
        plotPayload,
        gardenerHeaders
      );
      const plot = handleApiResponse<GardenPlot>(res, 201);

      assertGardenPlot(plot);
      expect(plot.plot_name).toBe('Sunny Corner Plot');
      expect(plot.plot_size_sqm).toBe(25.5);
      expect(plot.water_credits_per_liter).toBe(2.5);
      expect(plot.plan_id).toBe(plan.id);
    });

    it('should not create a Garden Plot under a non-existent plan', async () => {
      const plotPayload = generateGardenPlotPayload();
      const res = await apiClient.createGardenPlot(
        NON_EXISTENT_UUID,
        plotPayload,
        gardenerHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_FOUND });
    });

    it('should handle data isolation for a Garden Plot from a different plan', async () => {
      const planARes = await apiClient.createGardenPlan(
        { plan_name: 'Plan A Garden', total_water_credits: 5000 },
        gardenManagerHeaders
      );
      let planA = handleApiResponse<GardenPlan>(planARes, 201);

      planA = handleApiResponse<GardenPlan>(
        await apiClient.activateGardenPlan(planA.id, gardenManagerHeaders),
        200
      );

      const planBRes = await apiClient.createGardenPlan(
        { plan_name: 'Plan B Garden', total_water_credits: 5000 },
        gardenManagerHeaders
      );
      let planB = handleApiResponse<GardenPlan>(planBRes, 201);

      planB = handleApiResponse<GardenPlan>(
        await apiClient.activateGardenPlan(planB.id, gardenManagerHeaders),
        200
      );

      const plotRes = await apiClient.createGardenPlot(
        planB.id,
        {
          plot_name: 'Shaded Plot B',
          plot_size_sqm: 30,
          water_credits_per_liter: 3.0,
        },
        gardenerHeaders
      );
      const plotB = handleApiResponse<GardenPlot>(plotRes, 201);

      const res = await apiClient.getGardenPlot(planA.id, plotB.id, gardenManagerHeaders);
      validateErrorEnvelope(res, {
        expectedErrorId: ApiErrorId.ERR_PLOT_NOT_FOUND,
      });
    });

    it('should not get a non-existent Garden Plot', async () => {
      const planRes = await apiClient.createGardenPlan(generateGardenPlanPayload(), gardenManagerHeaders);
      const plan = handleApiResponse<GardenPlan>(planRes, 201);

      const res = await apiClient.getGardenPlot(plan.id, NON_EXISTENT_UUID, gardenManagerHeaders);
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PLOT_NOT_FOUND });
    });

    it('should add an amendment to a Garden Plot', async () => {
      const planRes = await apiClient.createGardenPlan(
        generateGardenPlanPayload(),
        gardenManagerHeaders
      );
      let plan = handleApiResponse<GardenPlan>(planRes, 201);

      plan = handleApiResponse<GardenPlan>(
        await apiClient.activateGardenPlan(plan.id, gardenManagerHeaders),
        200
      );

      const plotRes = await apiClient.createGardenPlot(
        plan.id,
        { plot_name: 'Acidic Plot', plot_size_sqm: 20, water_credits_per_liter: 2.0 },
        gardenerHeaders
      );
      const plot = handleApiResponse<GardenPlot>(plotRes, 201);

      const amendmentPayload = {
        name: AmendmentName.ACIDIC_SOIL,
        applied_date: generateAppliedDate(5),
      };

      const res = await apiClient.addAmendment(
        plan.id,
        plot.id,
        amendmentPayload,
        gardenerHeaders
      );
      const updatedPlot = handleApiResponse<GardenPlot>(res, 201);

      assertGardenPlot(updatedPlot);
      expect(updatedPlot.applied_amendments.length).toBe(1);
      expect(updatedPlot.applied_amendments[0].name).toBe(AmendmentName.ACIDIC_SOIL);
    });

    it('should not add an amendment to a non-existent Garden Plot', async () => {
      const planRes = await apiClient.createGardenPlan(
        generateGardenPlanPayload(),
        gardenManagerHeaders
      );
      let plan = handleApiResponse<GardenPlan>(planRes, 201);

      plan = handleApiResponse<GardenPlan>(
        await apiClient.activateGardenPlan(plan.id, gardenManagerHeaders),
        200
      );

      const amendmentPayload = {
        name: AmendmentName.FUNGICIDE_TREATED,
        applied_date: generateAppliedDate(0),
      };
      const res = await apiClient.addAmendment(
        plan.id,
        NON_EXISTENT_UUID,
        amendmentPayload,
        gardenerHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PLOT_NOT_FOUND });
    });
  });

  describe('TaskAssignment Resource', () => {
    it('should not create an Assignment under a non-existent plan', async () => {
      const assignmentPayload = {
        task_id: NON_EXISTENT_UUID,
        plot_id: NON_EXISTENT_UUID,
      };
      const res = await apiClient.createTaskAssignment(
        NON_EXISTENT_UUID,
        assignmentPayload,
        gardenerHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_FOUND });
    });

    it('should not perform operations on a non-existent Assignment', async () => {
      const planRes = await apiClient.createGardenPlan(generateGardenPlanPayload(), gardenManagerHeaders);
      let plan = handleApiResponse<GardenPlan>(planRes, 201);

      plan = handleApiResponse<GardenPlan>(
        await apiClient.activateGardenPlan(plan.id, gardenManagerHeaders),
        200
      );

      const res1 = await apiClient.getTaskAssignment(plan.id, NON_EXISTENT_UUID, gardenManagerHeaders);
      validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND });

      const res2 = await apiClient.approveTaskAssignment(
        plan.id,
        NON_EXISTENT_UUID,
        gardenManagerHeaders
      );
      validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND });

      const res3 = await apiClient.scheduleTaskAssignment(
        plan.id,
        NON_EXISTENT_UUID,
        gardenManagerHeaders
      );
      validateErrorEnvelope(res3, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND });
    });

    it('should handle data isolation when getting an Assignment from a different plan', async () => {
      const planARes = await apiClient.createGardenPlan(
        { plan_name: 'Plan A Garden', total_water_credits: 5000 },
        gardenManagerHeaders
      );
      let planA = handleApiResponse<GardenPlan>(planARes, 201);

      planA = handleApiResponse<GardenPlan>(
        await apiClient.activateGardenPlan(planA.id, gardenManagerHeaders),
        200
      );

      const planBRes = await apiClient.createGardenPlan(
        { plan_name: 'Plan B Garden', total_water_credits: 5000 },
        gardenManagerHeaders
      );
      let planB = handleApiResponse<GardenPlan>(planBRes, 201);

      planB = handleApiResponse<GardenPlan>(
        await apiClient.activateGardenPlan(planB.id, gardenManagerHeaders),
        200
      );

      const seasonRes = await apiClient.createPlantingSeason(
        planB.id,
        generatePlantingSeasonPayload(),
        gardenerHeaders
      );
      const season = handleApiResponse<PlantingSeason>(seasonRes, 201);

      const taskRes = await apiClient.createPlantingTask(
        planB.id,
        season.id,
        generatePlantingTaskPayload(),
        gardenerHeaders
      );
      const task = handleApiResponse<PlantingTask>(taskRes, 201);

      const plotRes = await apiClient.createGardenPlot(
        planB.id,
        generateGardenPlotPayload(),
        gardenerHeaders
      );
      const plot = handleApiResponse<GardenPlot>(plotRes, 201);

      const assignmentRes = await apiClient.createTaskAssignment(
        planB.id,
        { task_id: task.id, plot_id: plot.id },
        gardenerHeaders
      );
      const assignmentB = handleApiResponse<TaskAssignment>(assignmentRes, 201);

      const res = await apiClient.getTaskAssignment(
        planA.id,
        assignmentB.id,
        gardenManagerHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND });
    });

    it('should handle data isolation when rejecting an assignment from a different plan', async () => {
      const planARes = await apiClient.createGardenPlan(
        { plan_name: 'Plan A Garden', total_water_credits: 5000 },
        gardenManagerHeaders
      );
      let planA = handleApiResponse<GardenPlan>(planARes, 201);

      planA = handleApiResponse<GardenPlan>(
        await apiClient.activateGardenPlan(planA.id, gardenManagerHeaders),
        200
      );

      const planBRes = await apiClient.createGardenPlan(
        { plan_name: 'Plan B Garden', total_water_credits: 5000 },
        gardenManagerHeaders
      );
      let planB = handleApiResponse<GardenPlan>(planBRes, 201);

      planB = handleApiResponse<GardenPlan>(
        await apiClient.activateGardenPlan(planB.id, gardenManagerHeaders),
        200
      );

      const seasonRes = await apiClient.createPlantingSeason(
        planB.id,
        generatePlantingSeasonPayload(),
        gardenerHeaders
      );
      const season = handleApiResponse<PlantingSeason>(seasonRes, 201);

      const taskRes = await apiClient.createPlantingTask(
        planB.id,
        season.id,
        generatePlantingTaskPayload(),
        gardenerHeaders
      );
      const task = handleApiResponse<PlantingTask>(taskRes, 201);

      const plotRes = await apiClient.createGardenPlot(
        planB.id,
        generateGardenPlotPayload(),
        gardenerHeaders
      );
      const plot = handleApiResponse<GardenPlot>(plotRes, 201);

      const assignmentRes = await apiClient.createTaskAssignment(
        planB.id,
        { task_id: task.id, plot_id: plot.id },
        gardenerHeaders
      );
      const assignmentB = handleApiResponse<TaskAssignment>(assignmentRes, 201);

      const res = await apiClient.rejectTaskAssignment(
        planA.id,
        assignmentB.id,
        gardenManagerHeaders
      );

      validateErrorEnvelope(res, {
        expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND,
      });
    });
  });

  describe('PlotIncompatibility Resource', () => {
    it('should set plot incompatibilities', async () => {
      const planRes = await apiClient.createGardenPlan(
        generateGardenPlanPayload(),
        gardenManagerHeaders
      );
      let plan = handleApiResponse<GardenPlan>(planRes, 201);

      plan = handleApiResponse<GardenPlan>(
        await apiClient.activateGardenPlan(plan.id, gardenManagerHeaders),
        200
      );

      const plot1Res = await apiClient.createGardenPlot(
        plan.id,
        { plot_name: 'Tomato Plot', plot_size_sqm: 20, water_credits_per_liter: 2.0 },
        gardenerHeaders
      );
      const plot1 = handleApiResponse<GardenPlot>(plot1Res, 201);

      const plot2Res = await apiClient.createGardenPlot(
        plan.id,
        { plot_name: 'Fennel Plot', plot_size_sqm: 15, water_credits_per_liter: 2.0 },
        gardenerHeaders
      );
      const plot2 = handleApiResponse<GardenPlot>(plot2Res, 201);

      const incompatibilityPayload = {
        plot_ids: [plot2.id],
      };

      const res = await apiClient.setPlotIncompatibilities(
        plan.id,
        plot1.id,
        incompatibilityPayload,
        gardenManagerHeaders
      );
      const updatedPlot = handleApiResponse<GardenPlot>(res, 200);

      assertGardenPlot(updatedPlot);
      expect(updatedPlot.incompatible_plot_ids).toContain(plot2.id);
      expect(updatedPlot.incompatible_plot_ids.length).toBe(1);
    });

    it('should not set a plot as incompatible with itself', async () => {
      const planRes = await apiClient.createGardenPlan(
        generateGardenPlanPayload(),
        gardenManagerHeaders
      );
      let plan = handleApiResponse<GardenPlan>(planRes, 201);

      plan = handleApiResponse<GardenPlan>(
        await apiClient.activateGardenPlan(plan.id, gardenManagerHeaders),
        200
      );

      const plot1Res = await apiClient.createGardenPlot(
        plan.id,
        { plot_name: 'Self-referential Plot', plot_size_sqm: 20, water_credits_per_liter: 2.0 },
        gardenerHeaders
      );
      const plot1 = handleApiResponse<GardenPlot>(plot1Res, 201);

      const incompatibilityPayload = {
        plot_ids: [plot1.id],
      };

      const res = await apiClient.setPlotIncompatibilities(
        plan.id,
        plot1.id,
        incompatibilityPayload,
        gardenManagerHeaders
      );

      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_SELF_INCOMPATIBILITY });
    });

    it('should not set plot incompatibilities under a non-existent plan', async () => {
      const incompatibilityPayload = {
        plot_ids: [NON_EXISTENT_UUID],
      };
      const res = await apiClient.setPlotIncompatibilities(
        NON_EXISTENT_UUID,
        NON_EXISTENT_UUID,
        incompatibilityPayload,
        gardenManagerHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_FOUND });
    });

    it('should handle data isolation when setting incompatibility for a plot from a different plan', async () => {
      const planARes = await apiClient.createGardenPlan(
        { plan_name: 'Plan A Garden', total_water_credits: 5000 },
        gardenManagerHeaders
      );
      let planA = handleApiResponse<GardenPlan>(planARes, 201);

      planA = handleApiResponse<GardenPlan>(
        await apiClient.activateGardenPlan(planA.id, gardenManagerHeaders),
        200
      );

      const planBRes = await apiClient.createGardenPlan(
        { plan_name: 'Plan B Garden', total_water_credits: 5000 },
        gardenManagerHeaders
      );
      let planB = handleApiResponse<GardenPlan>(planBRes, 201);

      planB = handleApiResponse<GardenPlan>(
        await apiClient.activateGardenPlan(planB.id, gardenManagerHeaders),
        200
      );

      const plot1Res = await apiClient.createGardenPlot(
        planB.id,
        { plot_name: 'Plot One', plot_size_sqm: 20, water_credits_per_liter: 2.0 },
        gardenerHeaders
      );
      const plot1 = handleApiResponse<GardenPlot>(plot1Res, 201);

      const plot2Res = await apiClient.createGardenPlot(
        planB.id,
        { plot_name: 'Plot Two', plot_size_sqm: 15, water_credits_per_liter: 2.0 },
        gardenerHeaders
      );
      const plot2 = handleApiResponse<GardenPlot>(plot2Res, 201);

      const incompatibilityPayload = {
        plot_ids: [plot2.id],
      };

      const res = await apiClient.setPlotIncompatibilities(
        planA.id,
        plot1.id,
        incompatibilityPayload,
        gardenManagerHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PLOT_NOT_FOUND });
    });

    it('should not reference a non-existent plot in incompatibility list', async () => {
      const planRes = await apiClient.createGardenPlan(
        generateGardenPlanPayload(),
        gardenManagerHeaders
      );
      let plan = handleApiResponse<GardenPlan>(planRes, 201);

      plan = handleApiResponse<GardenPlan>(
        await apiClient.activateGardenPlan(plan.id, gardenManagerHeaders),
        200
      );

      const plotRes = await apiClient.createGardenPlot(
        plan.id,
        generateGardenPlotPayload(),
        gardenerHeaders
      );
      const plot = handleApiResponse<GardenPlot>(plotRes, 201);

      const incompatibilityPayload = {
        plot_ids: [NON_EXISTENT_UUID],
      };

      const res = await apiClient.setPlotIncompatibilities(
        plan.id,
        plot.id,
        incompatibilityPayload,
        gardenManagerHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INCOMPATIBLE_PLOT_NOT_FOUND });
    });
  });

  describe('Global Validations', () => {
    it('should handle User Context Header Validation', async () => {
      const res1 = await apiClient.getGardenPlans({} as any);
      validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });

      const headers2 = { 'X-User-Role': UserRole.GardenManager } as any;
      const res2 = await apiClient.getGardenPlans(headers2);
      validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });

      const headers3 = { 'X-User-ID': 'gm-1' } as any;
      const res3 = await apiClient.getGardenPlans(headers3);
      validateErrorEnvelope(res3, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });

      const invalidHeaders = {
        'X-User-ID': 'user-1',
        'X-User-Role': 'InvalidRole',
      } as any;
      const res4 = await apiClient.getGardenPlans(invalidHeaders);
      validateErrorEnvelope(res4, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });
    });
  });

  describe('Invalid plan creation requests', () => {
    it('should return ERR_INVALID_REQUEST when plan_name is missing', async () => {
      const payload = { total_water_credits: 5000 } as any;

      const res = await apiClient.createGardenPlan(payload, gardenManagerHeaders);

      validateErrorEnvelope(res, {
        expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST,
      });
    });

    it('should return ERR_INVALID_REQUEST when total_water_credits is missing', async () => {
      const payload = { plan_name: 'Incomplete Garden' } as any;

      const res = await apiClient.createGardenPlan(payload, gardenManagerHeaders);

      validateErrorEnvelope(res, {
        expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST,
      });
    });
  });
});
