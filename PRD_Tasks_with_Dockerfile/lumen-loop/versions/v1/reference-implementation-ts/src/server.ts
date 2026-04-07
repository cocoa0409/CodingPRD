import { openDb } from "./db";
import { createApp } from "./app";
import { registerRoutes } from "./routes";
import { ApiError } from "./errors";
import type express from "express";

const db = openDb();
const app = createApp(db);

registerRoutes(app, db);

app.use((err: unknown, _req: express.Request, res: express.Response, _next: express.NextFunction) => {
  if (err instanceof ApiError) {
    res.status(err.status).json({ error: { code: err.code, message: err.message } });
    return;
  }
  res.status(400).json({ error: { code: "ERR_INVALID_REQUEST", message: "Invalid request" } });
});

const port = Number(process.env.PORT) || 3000;
app.listen(port, () => {

  console.log(`LumenLoop API listening on ${port}`);
});
