import type express from "express";
import type { Db } from "../db";
import { registerProgramsRoutes } from "./programs";
import { registerSessionsRoutes } from "./sessions";
import { registerCustomersRoutes } from "./customers";
import { registerAdjustmentsRoutes } from "./adjustments";
import { registerBuildLotsRoutes } from "./buildLots";
import { registerOrdersRoutes } from "./orders";
import { registerPaymentsRoutes } from "./payments";
import { registerDevicesRoutes } from "./devices";
import { registerClaimsRoutes } from "./claims";
import { registerCarePlansRoutes } from "./carePlans";
import { registerTradeinsRoutes } from "./tradeins";
import { registerReturnsRoutes } from "./returns";
import { registerQualityCampaignRoutes } from "./qualityCampaigns";
import { registerAlertsRoutes } from "./alerts";

export function registerRoutes(app: express.Express, db: Db) {
  const requireSessionIfNeeded = (app as any).requireSessionIfNeeded as any;

  registerProgramsRoutes(app, db, requireSessionIfNeeded);
  registerSessionsRoutes(app, db, requireSessionIfNeeded);
  registerCustomersRoutes(app, db, requireSessionIfNeeded);
  registerAdjustmentsRoutes(app, db, requireSessionIfNeeded);
  registerBuildLotsRoutes(app, db, requireSessionIfNeeded);
  registerOrdersRoutes(app, db, requireSessionIfNeeded);
  registerPaymentsRoutes(app, db, requireSessionIfNeeded);
  registerDevicesRoutes(app, db, requireSessionIfNeeded);
  registerClaimsRoutes(app, db, requireSessionIfNeeded);
  registerCarePlansRoutes(app, db, requireSessionIfNeeded);
  registerTradeinsRoutes(app, db, requireSessionIfNeeded);
  registerReturnsRoutes(app, db, requireSessionIfNeeded);
  registerQualityCampaignRoutes(app, db, requireSessionIfNeeded);
  registerAlertsRoutes(app, db, requireSessionIfNeeded);
}
